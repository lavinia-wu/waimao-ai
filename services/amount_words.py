from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


_ONES = (
    'ZERO', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN',
    'EIGHT', 'NINE', 'TEN', 'ELEVEN', 'TWELVE', 'THIRTEEN', 'FOURTEEN',
    'FIFTEEN', 'SIXTEEN', 'SEVENTEEN', 'EIGHTEEN', 'NINETEEN',
)
_TENS = (
    '', '', 'TWENTY', 'THIRTY', 'FORTY', 'FIFTY', 'SIXTY', 'SEVENTY',
    'EIGHTY', 'NINETY',
)
_SCALES = ('', 'THOUSAND', 'MILLION', 'BILLION', 'TRILLION')
_CURRENCY_NAMES = {
    'AUD': ('AUSTRALIAN DOLLAR', 'AUSTRALIAN DOLLARS', 'CENT', 'CENTS'),
    'CAD': ('CANADIAN DOLLAR', 'CANADIAN DOLLARS', 'CENT', 'CENTS'),
    'CNY': ('CHINESE YUAN', 'CHINESE YUAN', 'FEN', 'FEN'),
    'EUR': ('EURO', 'EUROS', 'CENT', 'CENTS'),
    'GBP': ('POUND STERLING', 'POUNDS STERLING', 'PENNY', 'PENCE'),
    'HKD': ('HONG KONG DOLLAR', 'HONG KONG DOLLARS', 'CENT', 'CENTS'),
    'JPY': ('JAPANESE YEN', 'JAPANESE YEN', 'SEN', 'SEN'),
    'SGD': ('SINGAPORE DOLLAR', 'SINGAPORE DOLLARS', 'CENT', 'CENTS'),
    'USD': ('US DOLLAR', 'US DOLLARS', 'CENT', 'CENTS'),
}


def _under_one_thousand(number: int) -> str:
    words = []
    hundreds, remainder = divmod(number, 100)
    if hundreds:
        words.extend((_ONES[hundreds], 'HUNDRED'))
    if remainder:
        if words:
            words.append('AND')
        if remainder < 20:
            words.append(_ONES[remainder])
        else:
            tens, units = divmod(remainder, 10)
            words.append(_TENS[tens])
            if units:
                words.append(_ONES[units])
    return ' '.join(words)


def _integer_to_words(number: int) -> str:
    if number == 0:
        return 'ZERO'
    chunks = []
    scale_index = 0
    while number:
        number, chunk = divmod(number, 1000)
        if chunk:
            if scale_index >= len(_SCALES):
                raise ValueError('金额过大，无法转换为英文大写。')
            chunk_words = _under_one_thousand(chunk)
            scale = _SCALES[scale_index]
            chunks.append(f'{chunk_words} {scale}'.strip())
        scale_index += 1
    return ' '.join(reversed(chunks))


def amount_in_english_words(amount: object, currency: str = 'USD') -> str:
    try:
        value = Decimal(str(amount or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f'无法将金额转换为英文大写：{amount!r}') from exc

    negative = value < 0
    value = abs(value)
    integer_part = int(value)
    minor_part = int((value - integer_part) * 100)
    currency_code = currency.strip().upper()
    currency_singular, currency_plural, minor_singular, minor_plural = _CURRENCY_NAMES.get(
        currency_code,
        (currency_code, currency_code, 'CENT', 'CENTS'),
    )
    currency_unit = currency_singular if integer_part == 1 else currency_plural
    words = f'{_integer_to_words(integer_part)} {currency_unit}'
    if minor_part:
        minor_unit = minor_singular if minor_part == 1 else minor_plural
        words += f' AND {_integer_to_words(minor_part)} {minor_unit}'
    return f"{'MINUS ' if negative else ''}{words} ONLY"
