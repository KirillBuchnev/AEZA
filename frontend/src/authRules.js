// Mirrors backend/app/security.py so the form explains problems before sending.

export const USERNAME_PATTERN = /^[A-Za-z0-9._@-]{3,40}$/;
const WEAK_CODEWORDS = new Set(["password", "qwerty", "codeword", "letmein", "aeza"]);

// Python's len() and casefold() are closest to these: code points, and upper-then-lower folding.
const codePointLength = (value) => Array.from(value).length;
const fold = (value) => value.toUpperCase().toLowerCase();

export function normalizeCodeword(value) {
  return fold(value.split(/\s+/).filter(Boolean).join(" "));
}

export function usernameError(username) {
  if (!USERNAME_PATTERN.test(username))
    return "Логин должен быть от 3 до 40 символов: латинские буквы, цифры, точка, дефис, подчёркивание или @.";
  return "";
}

export function passwordError(password, username = "") {
  const length = codePointLength(password);
  if (length < 10 || length > 128) return "Пароль должен быть от 10 до 128 символов.";
  if (!(/\p{L}/u.test(password) && /\p{Nd}/u.test(password)))
    return "Пароль должен содержать буквы и цифры.";
  if (username && fold(password) === fold(username))
    return "Пароль не должен совпадать с логином.";
  return "";
}

export function matchError(first, second) {
  return first === second ? "" : "Пароли не совпадают.";
}

export function codewordError(codeword, password = "") {
  const normalized = normalizeCodeword(codeword);
  const length = codePointLength(normalized);
  if (length < 6 || length > 64) return "Кодовое слово должно быть от 6 до 64 символов.";
  if (/^\p{Nd}+$/u.test(normalized) || WEAK_CODEWORDS.has(normalized))
    return "Кодовое слово слишком простое: не только цифры и не типовое слово.";
  if (password && normalized === normalizeCodeword(password))
    return "Кодовое слово не должно совпадать с паролем.";
  return "";
}
