//! Bounded supervision of explicitly configured, trusted menu provider processes.
use std::{
    fmt,
    io::Read,
    process::{Child, Command, ExitStatus, Stdio},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
        mpsc,
    },
    time::{Duration, Instant},
};

use crate::config::{ConfigLoader, EntryConfig, ProviderConfig};
use crate::util::expand_tilde_str;

pub const MAX_PROVIDER_BYTES: usize = 1_048_576;

/// Failure to generate a new snapshot, or explicit foreground cancellation.
#[derive(Debug)]
pub enum ProviderError {
    Failure(String),
    Interrupted,
}

impl fmt::Display for ProviderError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Failure(message) => write!(formatter, "{message}"),
            Self::Interrupted => write!(formatter, "Provider interrupted"),
        }
    }
}
impl std::error::Error for ProviderError {}

/// The process boundary consumed by the deterministic menu lifecycle.
pub trait Provider {
    fn resolve(
        &mut self,
        provider: &ProviderConfig,
        depth: usize,
    ) -> Result<Vec<EntryConfig>, ProviderError>;
}

/// A provider's owned process group or kill-on-close Windows job.
struct ProcessTree {
    #[cfg(unix)]
    pid: i32,
    #[cfg(windows)]
    job: windows_sys::Win32::Foundation::HANDLE,
}

impl ProcessTree {
    fn attach(child: &Child) -> Result<Self, ProviderError> {
        #[cfg(unix)]
        {
            Ok(Self {
                pid: child.id() as i32,
            })
        }
        #[cfg(windows)]
        {
            use std::os::windows::io::AsRawHandle;
            use windows_sys::Win32::{Foundation::CloseHandle, System::JobObjects::*};
            // SAFETY: All pointers refer to live handles/POD storage; this job owns only our child.
            unsafe {
                let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
                if job.is_null() {
                    return Err(ProviderError::Failure(format!(
                        "Cannot create provider job: {}",
                        std::io::Error::last_os_error()
                    )));
                }
                let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                if SetInformationJobObject(
                    job,
                    JobObjectExtendedLimitInformation,
                    (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                    std::mem::size_of_val(&limits) as u32,
                ) == 0
                    || AssignProcessToJobObject(job, child.as_raw_handle()) == 0
                {
                    let error = std::io::Error::last_os_error();
                    CloseHandle(job);
                    return Err(ProviderError::Failure(format!(
                        "Cannot contain provider process: {error}"
                    )));
                }
                Ok(Self { job })
            }
        }
    }

    fn terminate(&mut self) {
        #[cfg(unix)]
        {
            // SAFETY: Negative pid selects the new process group created for our provider.
            let result = unsafe { libc::kill(-self.pid, libc::SIGKILL) };
            if result != 0 {
                log::debug!(
                    "Provider process group cleanup: {}",
                    std::io::Error::last_os_error()
                );
            }
        }
        #[cfg(windows)]
        if !self.job.is_null() {
            // SAFETY: This live job handle is closed at most once and kills only its assigned tree.
            unsafe {
                windows_sys::Win32::Foundation::CloseHandle(self.job);
            }
            self.job = std::ptr::null_mut();
        }
    }
}

struct ManagedChild {
    child: Child,
    tree: ProcessTree,
}

impl Drop for ManagedChild {
    fn drop(&mut self) {
        self.tree.terminate();
        if let Err(error) = self.child.kill() {
            log::debug!("Provider already stopped during cleanup: {error}");
        }
        if let Err(error) = self.child.wait() {
            log::warn!("Cannot reap provider: {error}");
        }
    }
}

/// Production provider executor; it is supervision, not a malicious-code sandbox.
pub struct MenuProvider {
    interrupted: Arc<AtomicBool>,
}

impl MenuProvider {
    pub fn new(interrupted: Arc<AtomicBool>) -> Self {
        Self { interrupted }
    }

    fn supervise(
        &self,
        managed: &mut ManagedChild,
        oversized: &AtomicBool,
        timeout: u64,
    ) -> Result<ExitStatus, ProviderError> {
        let deadline = Instant::now() + Duration::from_secs(timeout);
        loop {
            if self.interrupted.load(Ordering::SeqCst) {
                return Err(ProviderError::Interrupted);
            }
            if oversized.load(Ordering::SeqCst) {
                return Err(ProviderError::Failure(
                    "Provider output exceeds 1048576 bytes.".into(),
                ));
            }
            if Instant::now() >= deadline {
                return Err(ProviderError::Failure("Provider timed out.".into()));
            }
            if let Some(status) = managed.child.try_wait().map_err(|error| {
                ProviderError::Failure(format!("Cannot wait for provider: {error}"))
            })? {
                return Ok(status);
            }
            std::thread::sleep(Duration::from_millis(20));
        }
    }

    fn validate_json_depth(value: &serde_json::Value) -> Result<(), ProviderError> {
        let mut stack = vec![(value, 0)];
        while let Some((item, depth)) = stack.pop() {
            if item.is_array() || item.is_object() {
                if depth >= 64 {
                    return Err(ProviderError::Failure(
                        "Provider JSON nesting exceeds 64 containers.".into(),
                    ));
                }
                match item {
                    serde_json::Value::Array(items) => {
                        stack.extend(items.iter().map(|child| (child, depth + 1)))
                    }
                    serde_json::Value::Object(items) => {
                        stack.extend(items.values().map(|child| (child, depth + 1)))
                    }
                    _ => {}
                }
            }
        }
        Ok(())
    }

    fn execute(&self, provider: &ProviderConfig) -> Result<Vec<u8>, ProviderError> {
        if self.interrupted.load(Ordering::SeqCst) {
            return Err(ProviderError::Interrupted);
        }
        let entry = &provider.entry;
        let name = entry.command.to_lowercase();
        if name.ends_with(".bat") || name.ends_with(".cmd") {
            return Err(ProviderError::Failure(
                "Batch providers must explicitly invoke cmd.exe with argv.".into(),
            ));
        }
        let mut command = Command::new(&entry.command);
        command
            .args(&entry.args)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        command.envs(
            entry
                .env
                .iter()
                .map(|(key, value)| (key, expand_tilde_str(value))),
        );
        if let Some(directory) = &entry.working_directory {
            command.current_dir(directory);
        }
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            command.process_group(0);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x0000_0200);
        }
        let mut child = command
            .spawn()
            .map_err(|error| ProviderError::Failure(format!("Cannot start provider: {error}")))?;
        let tree = match ProcessTree::attach(&child) {
            Ok(tree) => tree,
            Err(error) => {
                if let Err(cleanup) = child.kill() {
                    log::debug!("Provider startup cleanup: {cleanup}");
                }
                if let Err(cleanup) = child.wait() {
                    log::warn!("Cannot reap failed provider: {cleanup}");
                }
                return Err(error);
            }
        };
        let mut managed = ManagedChild { child, tree };
        let stdout = managed
            .child
            .stdout
            .take()
            .ok_or_else(|| ProviderError::Failure("Provider stdout unavailable.".into()))?;
        let (sender, receiver) = mpsc::channel();
        let oversized = Arc::new(AtomicBool::new(false));
        let size_flag = oversized.clone();
        let reader = std::thread::Builder::new()
            .name("menu-provider-stdout".into())
            .spawn(move || {
                let mut output = Vec::new();
                let result = stdout
                    .take((MAX_PROVIDER_BYTES + 1) as u64)
                    .read_to_end(&mut output)
                    .map(|_| output);
                if let Ok(bytes) = &result {
                    size_flag.store(bytes.len() > MAX_PROVIDER_BYTES, Ordering::SeqCst);
                }
                if sender.send(result).is_err() {
                    log::debug!("Provider output receiver was closed");
                }
            })
            .map_err(|error| {
                ProviderError::Failure(format!("Cannot read provider output: {error}"))
            })?;
        let status = self.supervise(&mut managed, &oversized, provider.timeout_seconds);
        drop(managed);
        let captured = receiver.recv_timeout(Duration::from_secs(2));
        if captured.is_ok() && reader.join().is_err() {
            return Err(ProviderError::Failure(
                "Provider output reader failed.".into(),
            ));
        }
        let status = status?;
        let bytes = captured
            .map_err(|_| {
                ProviderError::Failure("Provider output did not close after cleanup.".into())
            })?
            .map_err(|error| {
                ProviderError::Failure(format!("Cannot read provider output: {error}"))
            })?;
        if bytes.len() > MAX_PROVIDER_BYTES {
            return Err(ProviderError::Failure(
                "Provider output exceeds 1048576 bytes.".into(),
            ));
        }
        if !status.success() {
            return Err(ProviderError::Failure(format!(
                "Provider exited with status {status}."
            )));
        }
        Ok(bytes)
    }
}

impl Provider for MenuProvider {
    fn resolve(
        &mut self,
        provider: &ProviderConfig,
        depth: usize,
    ) -> Result<Vec<EntryConfig>, ProviderError> {
        let bytes = self.execute(provider)?;
        let text = std::str::from_utf8(&bytes)
            .map_err(|error| ProviderError::Failure(format!("Invalid provider UTF-8: {error}")))?;
        let mut raw: serde_json::Value = serde_json::from_str(text)
            .map_err(|error| ProviderError::Failure(format!("Invalid provider JSON: {error}")))?;
        Self::validate_json_depth(&raw)?;
        let entries = raw
            .as_object_mut()
            .and_then(|table| table.remove("entries"))
            .ok_or_else(|| {
                ProviderError::Failure("Provider output requires an entries array.".into())
            })?;
        ConfigLoader::parse_entries(entries, depth)
            .map_err(|error| ProviderError::Failure(format!("Invalid provider result: {error}")))
    }
}
