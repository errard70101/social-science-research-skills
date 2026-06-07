# Title Case and BibTeX Protection

Use Chicago-style headline capitalization:

- Capitalize the first and last word.
- Capitalize major words.
- Capitalize the first word after a colon.
- Lowercase articles, coordinating conjunctions, and short prepositions unless
  they are first, last, or follow a colon.

Protect case-sensitive content with braces:

```bibtex
title = {The Effects of {AI} on {U.S.} Labor Markets}
```

Preserve braces around:

- Initialisms and abbreviations.
- Proper names and case-sensitive technical terms.
- LaTeX commands and their arguments.
- Inline mathematics.

Add protection only when the publication title and reliable sources support
the capitalization. The helper performs mechanical headline capitalization;
the verifier remains responsible for semantic case protection.

