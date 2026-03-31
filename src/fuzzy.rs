//! Fuzzy substring matching with scoring.
//!
//! Scores how well a short query string matches against a longer candidate
//! using an ordered, non-contiguous character-matching algorithm with bonuses
//! for contiguous runs and word-boundary alignment.

pub struct FuzzyMatcher;

impl FuzzyMatcher {
    /// Score how well `query` fuzzy-matches `candidate`.
    ///
    /// All characters in `query` must appear in `candidate` in order (not
    /// necessarily contiguous). Higher scores indicate better matches, with
    /// bonuses for contiguous runs and word-boundary alignment.
    ///
    /// Returns `Some(score)` on match, `None` if the query does not match.
    pub fn score(query: &str, candidate: &str) -> Option<i32> {
        if query.is_empty() {
            return Some(0);
        }

        let query_lower: Vec<char> = query.to_lowercase().chars().collect();
        let candidate_lower: Vec<char> = candidate.to_lowercase().chars().collect();

        let mut q_idx = 0;
        let mut score: i32 = 0;
        let mut prev_match_idx: i32 = -2;

        for (c_idx, &c_char) in candidate_lower.iter().enumerate() {
            if q_idx < query_lower.len() && c_char == query_lower[q_idx] {
                score += 1;
                // Contiguous character bonus
                if c_idx as i32 == prev_match_idx + 1 {
                    score += 2;
                }
                // Word-boundary bonus
                if c_idx == 0
                    || matches!(
                        candidate_lower[c_idx - 1],
                        ' ' | '-' | '_' | '.' | '/' | '\\'
                    )
                {
                    score += 3;
                }
                prev_match_idx = c_idx as i32;
                q_idx += 1;
            }
        }

        if q_idx < query_lower.len() {
            return None;
        }

        Some(score)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_query_returns_zero() {
        assert_eq!(
            FuzzyMatcher::score("", "anything"),
            Some(0),
            "empty query should score 0"
        );
    }

    #[test]
    fn exact_match_scores_high() {
        let s = FuzzyMatcher::score("abc", "abc");
        assert!(s.is_some(), "exact match should succeed");
        assert!(s.unwrap() > 0, "exact match should have positive score");
    }

    #[test]
    fn no_match_returns_none() {
        assert_eq!(
            FuzzyMatcher::score("xyz", "abc"),
            None,
            "non-matching should return None"
        );
    }

    #[test]
    fn case_insensitive() {
        let s = FuzzyMatcher::score("ABC", "abcdef");
        assert!(s.is_some(), "case-insensitive match should succeed");
    }

    #[test]
    fn contiguous_scores_higher_than_sparse() {
        let contiguous = FuzzyMatcher::score("ab", "xabx").unwrap();
        let sparse = FuzzyMatcher::score("ab", "xaxbx").unwrap();
        assert!(
            contiguous > sparse,
            "contiguous run should score higher than sparse: {contiguous} vs {sparse}"
        );
    }

    #[test]
    fn word_boundary_bonus() {
        let boundary = FuzzyMatcher::score("c", "ab cd").unwrap();
        let mid_word = FuzzyMatcher::score("b", "ab cd").unwrap();
        assert!(
            boundary > mid_word,
            "word-boundary match should score higher: {boundary} vs {mid_word}"
        );
    }

    #[test]
    fn subsequence_match() {
        let s = FuzzyMatcher::score("ac", "abcdef");
        assert!(s.is_some(), "subsequence should match");
    }
}
