# SPEC: data-driven currency formatting with `register_currency`

## Goal
`ledger.money.format_money` hard-codes one `if` branch per currency, and
finance keeps asking engineering to add currencies. Restructure
`ledger/money.py` so that every currency, built-in or added later, is
described by data in a single registry that `format_money` looks up, and add
a public `register_currency` function so new currencies can be added without
touching `format_money`. This is a refactor: the output for the five built-in
currencies must not change at all.

## Current behavior
`format_money(amount, currency)` supports USD, GBP, EUR, CHF and JPY via
separate branches with duplicated logic, for example:

| call | result |
| --- | --- |
| `format_money(123456, 'USD')` | `$1,234.56` |
| `format_money(-5, 'GBP')` | `-£0.05` |
| `format_money(-123456, 'EUR')` | `-1.234,56 €` |
| `format_money(-123456, 'CHF')` | `CHF -1'234.56` |
| `format_money(1234567, 'jpy')` | `¥1,234,567` |

Currency codes are case-insensitive; a non-`int` amount (including `bool`)
raises `TypeError`; an unsupported code raises `UnknownCurrencyError` (a
subclass of `ValueError`). There is no way to add a currency.

## Desired behavior

1. **Behavior preservation.** For USD, GBP, EUR, CHF and JPY, `format_money`
   returns exactly what the current implementation returns for every `int`
   amount (positive, zero, negative, any size) and every letter case of the
   code. The `TypeError` and `UnknownCurrencyError` behavior is unchanged.
2. **One registry.** The five built-in currencies are registered in the same
   registry that `register_currency` adds to, so registering any of their codes
   again (in any letter case) raises `ValueError`.
3. **New API.**
   `ledger.money.register_currency(code, symbol, *, decimals=2, thousands_sep=',', decimal_sep='.', position='prefix', space=False) -> None`
   registers a currency. Validation (each failure raises `ValueError` and
   leaves the registry unchanged):
   - `code` must be a string of exactly three ASCII letters; it is
     case-insensitive (`'sek'` registers `SEK`) and must not already be
     registered.
   - `symbol` must be a non-empty string.
   - `decimals` must be an `int` from 0 to 4.
   - `position` must be `'prefix'` or `'suffix'`.
   `thousands_sep` and `decimal_sep` are strings; an empty `thousands_sep`
   means no grouping.
4. **Formatting rule** (used for every registered currency, and consistent
   with the built-ins' current output). With `whole, fraction =
   divmod(abs(amount), 10 ** decimals)`:
   - the *number* is `whole` written in groups of three digits from the right,
     joined by `thousands_sep`, followed, when `decimals > 0`, by
     `decimal_sep` and `fraction` zero-padded to `decimals` digits
     (`decimals == 0` means no decimal separator at all);
   - the *body* is `symbol + number` for `'prefix'` and `number + symbol` for
     `'suffix'`, with a single space between symbol and number when
     `space=True`;
   - for a negative amount, `-` is placed at the very start of the result,
     except for a `'prefix'` symbol with `space=True`, where it goes directly
     before the number (`CHF -1'234.56`).
   After `register_currency`, `format_money(amount, code)` formats with the
   new currency, and its code is case-insensitive like the built-ins.

## Allowed paths
- `ledger/`
- `tests/`

## Non-goals
- No unregistering or replacing currencies, no parsing, no rounding (amounts
  are already integers in minor units), no locale support.
- No change to `format_money`'s signature or exception classes.
- No third-party dependencies; Python 3.8+ standard library only.

## Acceptance criteria
- Every rule above holds; every built-in output is byte-for-byte identical to
  the current implementation.
- The visible test suite passes; add tests for the new API and for the
  built-in outputs you relied on while refactoring.

## Test commands
- `python3 -m unittest discover -s tests -v`

## Handoff
Report the files you changed, how the built-ins are now defined, and the test
command output.
