# Python Testing

Test-writing practices for pytest, trimmed to the rules that fit this repo.
`CLAUDE.md`, `tests/conftest.py` and `tests/common.py` take precedence over
the examples here.

## Overview

This skill provides 8 rules across 4 categories:

| Category | Prefix | Impact | Rules |
|----------|--------|--------|-------|
| Mocking | `mock-` | CRITICAL | 1 |
| Test Structure | `struct-` | HIGH | 3 |
| Fixtures | `fixture-` | HIGH | 2 |
| Parametrization | `param-` | MEDIUM | 2 |

## Structure

```
.claude/skills/testing/
├── SKILL.md                   # Skill overview, repo conventions, quick reference
├── metadata.json              # Metadata (version, description)
├── README.md                  # This file
└── rules/
    ├── _sections.md           # Section definitions
    ├── _template.md           # Rule template
    ├── mock-boundaries.md     # Mock external boundaries only
    ├── struct-test-naming.md  # Behavior-based names
    ├── struct-one-behavior.md # One behavior per test
    ├── struct-no-logic.md     # No conditionals/loops in tests
    ├── fixture-scope.md       # Narrowest scope that works
    ├── fixture-factory.md     # Factory fixtures
    ├── param-parametrize.md   # Case tables with parametrize
    └── param-ids.md           # Readable case ids
```

## Usage

This skill is automatically applied when working with test files (`tests/**`, `test_*.py`, `*_test.py`, `conftest.py`).
