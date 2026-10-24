# Section Definitions

## Mocking (mock)
**Impact:** CRITICAL

Mock external boundaries only.
Covers what to mock (the `Hive` session and `Auth` client from `apyhiveapi`) and what not to (the integration's own entities, flows and services).

**Rules:**
- `mock-boundaries` - Mock external boundaries, not internal logic

## Test Structure (struct)
**Impact:** HIGH

Structure tests so failures are easy to diagnose.
Covers behavior-based naming, test granularity, and keeping logic out of test bodies.

**Rules:**
- `struct-test-naming` - Name tests after the behavior they verify
- `struct-one-behavior` - Test one behavior per test
- `struct-no-logic` - Keep conditionals and loops out of tests

## Fixtures (fixture)
**Impact:** HIGH

Share setup without hiding it.
Covers fixture scoping for isolation and factory fixtures for varied test data.

**Rules:**
- `fixture-scope` - Use the narrowest fixture scope that works
- `fixture-factory` - Use factory fixtures for varied test data

## Parametrization (param)
**Impact:** MEDIUM

Eliminate duplicated tests without hiding cases.
Covers pytest.mark.parametrize for case tables and readable ids for failure reports.

**Rules:**
- `param-parametrize` - Replace duplicated tests with parametrize
- `param-ids` - Give parametrized cases readable ids
