//! Session-owned nested menu snapshots and explicit navigation lifecycle.
use crate::{
    config::{EntryConfig, LaunchLineConfig, MenuConfig},
    providers::{MenuProvider, Provider, ProviderError},
};
use std::{
    cell::{Ref, RefCell},
    rc::Rc,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
};

/// Stable explicit ids preserve selection; otherwise the full declaration must match.
pub fn same_entry(previous: &EntryConfig, current: &EntryConfig) -> bool {
    if !previous.id.is_empty() && !current.id.is_empty() {
        previous.id == current.id
    } else {
        previous == current
    }
}

/// View state references identities rather than row numbers after regeneration.
#[derive(Debug, Clone, Default)]
pub struct ViewState {
    pub query: String,
    pub cursor: usize,
    pub selected: Option<EntryConfig>,
    pub viewport: usize,
}

/// One cached menu instance; children never retain references to their parents.
const MAX_CACHED_MENUS: usize = 128;

pub struct MenuFrame {
    pub declaration: MenuConfig,
    pub origin: Option<EntryConfig>,
    pub entries: Vec<EntryConfig>,
    pub loaded: bool,
    last_used: u64,
    pub error: Option<String>,
    pub view: ViewState,
    pub children: Vec<Rc<RefCell<MenuFrame>>>,
}

impl MenuFrame {
    fn new(declaration: MenuConfig, origin: Option<EntryConfig>) -> Self {
        Self {
            declaration,
            origin,
            entries: vec![],
            loaded: false,
            last_used: 0,
            error: None,
            view: ViewState::default(),
            children: vec![],
        }
    }
}

/// A bounded stack with per-session cached descendants and last-good snapshots.
type LoadObserver = Box<dyn Fn(&str)>;

pub struct MenuSession<P: Provider> {
    provider: P,
    clock: u64,
    stack: Vec<Rc<RefCell<MenuFrame>>>,
    observer: Option<LoadObserver>,
}

impl<P: Provider> MenuSession<P> {
    pub fn new(config: &LaunchLineConfig, provider: P) -> Self {
        let declaration = MenuConfig {
            entries: config.entries.clone(),
            title: config.title.clone(),
            provider: config.provider.clone(),
            refresh_on_return: config.refresh_on_return,
        };
        Self {
            provider,
            clock: 0,
            observer: None,
            stack: vec![Rc::new(RefCell::new(MenuFrame::new(declaration, None)))],
        }
    }
    pub fn with_observer(mut self, observer: impl Fn(&str) + 'static) -> Self {
        self.observer = Some(Box::new(observer));
        self
    }
    pub fn current(&self) -> Ref<'_, MenuFrame> {
        self.stack.last().expect("root menu is retained").borrow()
    }
    pub fn depth(&self) -> usize {
        self.stack.len()
    }
    pub fn title(&self) -> String {
        self.stack
            .iter()
            .map(|frame| frame.borrow().declaration.title.clone())
            .collect::<Vec<_>>()
            .join(" / ")
    }
    pub fn set_view(&self, view: ViewState) {
        self.stack
            .last()
            .expect("root menu is retained")
            .borrow_mut()
            .view = view;
    }

    pub fn ensure_loaded(&mut self) -> Result<(), ProviderError> {
        if !self.current().loaded {
            self.refresh()?;
        }
        Ok(())
    }

    /// Replace the snapshot only on success, retaining old entries on provider failure.
    pub fn refresh(&mut self) -> Result<bool, ProviderError> {
        self.touch();
        let pointer = self.stack.last().expect("root menu is retained").clone();
        pointer.borrow_mut().loaded = true;
        let declaration = pointer.borrow().declaration.clone();
        if declaration.provider.is_some()
            && let Some(observer) = &self.observer
        {
            observer(&declaration.title);
        }
        let result = match &declaration.provider {
            Some(provider) => self.provider.resolve(provider, self.depth() - 1),
            None => Ok(declaration.entries),
        };
        let entries = match result {
            Ok(entries) => entries,
            Err(ProviderError::Interrupted) => return Err(ProviderError::Interrupted),
            Err(error) => {
                log::error!("Menu provider failed: {error}");
                pointer.borrow_mut().error = Some(error.to_string());
                return Ok(false);
            }
        };
        let mut frame = pointer.borrow_mut();
        frame.entries = entries;
        frame.error = None;
        let MenuFrame {
            entries, children, ..
        } = &mut *frame;
        children.retain(|child| {
            let child = child.borrow();
            child.origin.as_ref().is_some_and(|origin| {
                entries.iter().any(|entry| {
                    same_entry(origin, entry) && entry.menu.as_deref() == Some(&child.declaration)
                })
            })
        });
        Ok(true)
    }

    pub fn open(&mut self, entry: &EntryConfig) -> Result<(), ProviderError> {
        let Some(declaration) = &entry.menu else {
            return Err(ProviderError::Failure(
                "Only a current submenu can be opened.".into(),
            ));
        };
        if !self.current().entries.contains(entry) {
            return Err(ProviderError::Failure(
                "Only a current submenu can be opened.".into(),
            ));
        }
        if self.depth() >= 16 {
            return Err(ProviderError::Failure(
                "Menus may be nested at most 16 levels including root.".into(),
            ));
        }
        let parent = self.stack.last().expect("root menu is retained").clone();
        let cached = parent
            .borrow()
            .children
            .iter()
            .find(|child| {
                let child = child.borrow();
                child
                    .origin
                    .as_ref()
                    .is_some_and(|previous| same_entry(previous, entry))
                    && child.declaration == **declaration
            })
            .cloned();
        let child = cached.unwrap_or_else(|| {
            let child = Rc::new(RefCell::new(MenuFrame::new(
                (**declaration).clone(),
                Some(entry.clone()),
            )));
            parent.borrow_mut().children.push(child.clone());
            child
        });
        self.stack.push(child);
        self.ensure_loaded()?;
        self.touch();
        self.evict();
        Ok(())
    }

    fn touch(&mut self) {
        self.clock = self.clock.saturating_add(1);
        self.stack
            .last()
            .expect("root menu is retained")
            .borrow_mut()
            .last_used = self.clock;
    }

    fn evict(&mut self) {
        loop {
            let mut frames = vec![(self.stack[0].clone(), None)];
            let mut index = 0;
            while index < frames.len() {
                let parent = frames[index].0.clone();
                let children = parent.borrow().children.clone();
                frames.extend(
                    children
                        .into_iter()
                        .map(|child| (child, Some(parent.clone()))),
                );
                index += 1;
            }
            if frames.len() <= MAX_CACHED_MENUS {
                return;
            }
            let candidate = frames
                .into_iter()
                .filter(|(frame, parent)| {
                    parent.is_some() && !self.stack.iter().any(|active| Rc::ptr_eq(active, frame))
                })
                .min_by_key(|(frame, _)| frame.borrow().last_used);
            let Some((frame, Some(parent))) = candidate else {
                return;
            };
            parent
                .borrow_mut()
                .children
                .retain(|child| !Rc::ptr_eq(child, &frame));
        }
    }

    pub fn back(&mut self) -> Result<bool, ProviderError> {
        if self.depth() == 1 {
            return Ok(false);
        }
        self.stack.pop();
        self.touch();
        let regenerate = {
            let frame = self.current();
            frame.declaration.refresh_on_return && frame.declaration.provider.is_some()
        };
        if regenerate {
            self.refresh()?;
        }
        Ok(true)
    }
}

/// Compose the existing renderer and command runner with the menu state machine.
pub fn run(config: LaunchLineConfig, interrupted: Arc<AtomicBool>) -> i32 {
    use crate::{
        runner::EntryRunner,
        ui::{LaunchLineUI, MenuIntent},
    };
    let mut session = MenuSession::new(&config, MenuProvider::new(interrupted.clone()))
        .with_observer(|title| eprintln!("Loading menu: {title}"));
    loop {
        if session.ensure_loaded().is_err() {
            return 130;
        }
        let frame = session.current();
        let mut visible = LaunchLineConfig {
            entries: frame.entries.clone(),
            title: String::new(),
            on_exit: config.on_exit.clone(),
            show_exit: config.show_exit,
            clear_on_launch: config.clear_on_launch,
            ghost_text: config.ghost_text,
            numeric_trigger: config.numeric_trigger,
            provider: None,
            refresh_on_return: false,
        };
        let refresh_index = if frame.declaration.provider.is_some() {
            let index = visible.entries.len();
            visible.entries.push(control(
                if frame.error.is_some() {
                    "Retry provider"
                } else {
                    "Refresh menu"
                },
                "Regenerate this menu (Ctrl+R)",
            ));
            Some(index)
        } else {
            None
        };
        let back_index = if session.depth() > 1 {
            let index = visible.entries.len();
            visible
                .entries
                .push(control("Back", "Return to parent menu"));
            Some(index)
        } else {
            None
        };
        let status = if frame.error.is_some() {
            " [provider failed]"
        } else if frame.entries.is_empty() {
            " [empty]"
        } else {
            ""
        };
        visible.title = session.title() + status;
        let state = frame.view.clone();
        drop(frame);
        let mut ui = LaunchLineUI::new(&visible);
        let (choice, state) = ui.choose(&state);
        session.set_view(state);
        if choice.intent == MenuIntent::Refresh
            || choice
                .index
                .is_some_and(|index| Some(index) == refresh_index)
        {
            if session.refresh().is_err() {
                return 130;
            }
            continue;
        }
        if choice.intent == MenuIntent::Back
            || choice.index.is_some_and(|index| Some(index) == back_index)
        {
            match session.back() {
                Ok(true) => continue,
                Ok(false) => return 0,
                Err(_) => return 130,
            }
        }
        let Some(index) = choice.index else {
            return 0;
        };
        let entry = &visible.entries[index];
        if entry.menu.is_some() {
            match session.open(entry) {
                Err(ProviderError::Interrupted) => return 130,
                Err(error) => log::error!("Cannot open menu: {error}"),
                Ok(()) => {}
            }
            continue;
        }
        interrupted.store(false, Ordering::SeqCst);
        let result = EntryRunner::new(&config).launch(entry);
        let code = if interrupted.swap(false, Ordering::SeqCst) {
            130
        } else {
            match result {
                Ok(code) => code,
                Err(error) => {
                    log::error!("Cannot launch entry: {error}");
                    1
                }
            }
        };
        if config.on_exit == "exit" {
            return code;
        }
    }
}

fn control(name: &str, description: &str) -> EntryConfig {
    EntryConfig {
        name: name.into(),
        command: String::new(),
        args: vec![],
        description: description.into(),
        working_directory: None,
        env: Default::default(),
        id: String::new(),
        menu: None,
    }
}
