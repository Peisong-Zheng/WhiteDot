import unittest

from whitedot.local_spelling import check_local


class LocalSpellingTests(unittest.TestCase):
    def test_common_misspellings_and_unicode_offsets(self):
        text = "🙂 I can definately recieve teh accomodation in a seperate building."
        issues = check_local(text)
        self.assertEqual([i.suggestions[0] for i in issues],
                         ["definitely", "receive", "the", "accommodation", "separate"])
        for issue in issues:
            self.assertEqual(text[issue.start:issue.end], issue.original)

    def test_skips_names_dialects_urls_identifiers_and_code(self):
        text = ("Meet Anne Teh in Zürich. Colour, centre, organise, and naïve are fine. "
                "See teh.example.com, https://host/recieve, a@teh.example, _teh_, tehCount, "
                "TEH, `teh recieve` or ```\nShe go to teh\n```. I will recieve it.")
        self.assertEqual([(i.original, i.start) for i in check_local(text)],
                         [("recieve", text.rindex("recieve"))])

    def test_whole_words_start_case_and_contractions(self):
        issues = check_local("Teh boat: I dont know; aTeh and teh100 are codes.")
        self.assertEqual([(i.original, i.suggestions[0]) for i in issues],
                         [("Teh", "The"), ("dont", "don't")])

    def test_local_grammar_only_at_clear_sentence_boundaries(self):
        text = "She go to school. It is possible that she go.\nThey is here. He don’t remember."
        issues = check_local(text)
        self.assertEqual([(i.original, i.suggestions[0]) for i in issues],
                         [("go", "goes"), ("is", "are"), ("don’t", "doesn’t")])

    def test_correct_pronoun_verb_pairs_and_contractions(self):
        forms = [
            (("I",), ("am", "have", "go", "do", "don't", "don’t")),
            (("He", "She", "It"), ("is", "has", "goes", "does", "doesn't", "doesn’t")),
            (("We", "You", "They"), ("are", "have", "go", "do", "don't", "don’t")),
        ]
        for subjects, verbs in forms:
            for subject in subjects:
                for verb in verbs:
                    with self.subTest(subject=subject, verb=verb):
                        self.assertEqual(check_local(f"{subject} {verb}."), [])
        self.assertEqual(check_local("I'm ready. She’s early. They've left. We’re happy."), [])

    def test_repeated_word_removes_extra_space_and_preserves_deliberate_repetition(self):
        text = "I know that that happened; I had had the  the book."
        issues = check_local(text)
        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertEqual(text[:issue.start] + issue.suggestions[0] + text[issue.end:],
                         "I know that that happened; I had had the book.")

    def test_pathological_pastes_are_bounded_and_nonoverlapping(self):
        text = "the the the teh " * 1500
        issues = check_local(text)
        self.assertLessEqual(len(issues), 128)
        self.assertTrue(all(a.end <= b.start for a, b in zip(issues, issues[1:])))


if __name__ == "__main__":
    unittest.main()
