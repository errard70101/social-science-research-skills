# Section Rubric

Target lengths are guidance, not hard limits. The renderer emits a warning
when a slot falls more than 25 percent outside its band. Always favor
accuracy and intuition over hitting an exact word count.

| Section                              | Sentences | Words   |
|--------------------------------------|-----------|---------|
| In one sentence                      | 1         | 20-35   |
| Setup                                | 2-4       | 60-120  |
| Empirical strategy                   | 3-5       | 90-160  |
| Identification, in plain English     | 3-5       | 90-160  |
| Key result                           | 2-3       | 50-110  |
| Where this sits                      | 3-5       | 90-160  |
| Limitations                          | 2-3       | 50-100  |
| Follow-ups                           | 2-3       | 50-100  |

## Writing Style

- **Audience:** an economics PhD outside the paper's subfield. Assume working
  knowledge of OLS, IV, RD, DiD, and standard panel methods; do not assume
  familiarity with subfield-specific jargon.
- **Tone:** descriptive and neutral. The summary is for both private reference
  and sharing with a colleague.
- **Numbers:** every coefficient, standard error, sample size, or claim of
  statistical significance must trace to a specific page in the source PDF.
  Include inline page references (for example, "(p.~11)") for every numeric
  claim.
- **Methodology terms:** prefer plain-English mechanisms over jargon. "The
  authors compare counties on either side of a redistricting boundary" beats
  "geographic regression discontinuity at the redistricting boundary."

## LaTeX in Section Bodies

Section bodies are inserted into the template verbatim, so they are
LaTeX-as-typed. Use this freedom for citations and math, but escape any
literal special characters that you mean as plain text:

- Citations: write `{{authorYearFirstWord}}` for inline references; the
  renderer expands these to `\citep{...}`. Raw `\cite{...}` calls are also
  honored.
- Math: wrap with `$...$` or `$$...$$` as usual.
- Plain-text specials: escape `%` as `\%`, `&` as `\&`, `_` as `\_`,
  `#` as `\#`, and `$` as `\$` when you mean a literal character (for
  example, "10\% margin", "panel A\&B", "real\_gdp\_pc",
  "covers \#1 and \#2", "\$2{,}500 incentive"). Leaving these unescaped
  will break compilation.
- The non-breaking space `~` is a deliberate typographic spacing command
  (for example, in "p.~11") — leave it unescaped in that usage.

## Per-Section Notes

### In one sentence

One declarative sentence that names the question, the answer, and (if a
single instrument or experiment carries the paper) the source of variation.

> Example: "Settler mortality predicts modern institutional quality and,
> through it, contemporary income, because high-mortality colonies received
> extractive rather than inclusive institutions."

### Setup

What is the question, what is the unit of observation, what is the sample,
and over what time period? Two to four sentences.

### Empirical strategy

Name the estimator and the headline specification. Identify the source of
exogenous variation. Do not paraphrase the regression equation; the agent
should write the equation only when it is essential to understanding the
identification, and only when the LaTeX in the source paper is available.

### Identification, in plain English

This is the highest-leverage section of the summary. Explain the comparison
the paper makes as if at a whiteboard. State what would have to be true for
the comparison to be causal. State the threats to that assumption that the
paper directly addresses.

> Example: "Two countries that look similar today could differ only because
> their colonizers faced different disease environments centuries ago. If
> settler mortality affected modern income only through the institutions it
> shaped, the comparison is causal. The paper rules out direct effects of
> climate and disease by controlling for latitude and contemporary disease
> prevalence."

### Key result

Headline magnitude with units, plus the one alternative specification that
either confirms or qualifies it. Inline page references for each number.

### Where this sits

One paragraph placing the paper among the two or three predecessors it
explicitly engages with in its related-work or introduction sections. Use
`\cite{}` calls with keys following the `authorYearFirstWord` convention.
When no clear predecessor is identifiable, this section is prose-only and
`predecessor_citations` is empty.

### Limitations

The limitations the paper itself acknowledges, plus at most one limitation
that a non-subfield reader is likely to notice. Do not invent limitations.

### Follow-ups

What does this paper open up that the next paper should pick up? At most one
sentence each for two or three follow-ups.

## Author Names

When writing summary content JSON:
- If author names are ambiguous or contain multi-word surnames (e.g. `De Long`, `van der Weide`), prefer using the `Lastname, Firstname` format in the `authors` list (e.g. `["De Long, J. B.", "van der Weide, Roy"]`). This format ensures unambiguous surname extraction.

## Do Not

- Do not invent coefficients, standard errors, sample sizes, statistical
  significance, journal names, or predecessor citations.
- Do not OCR or paraphrase econometric tables; use the page-snapshot image mode
  for the headline visual unless you can supply LaTeX directly from the source.
- Do not write the summary from memory of the paper. Read the extracted text
  for every claim.
