import { useRef, useState } from "react";
import { api } from "./api.js";
import mascot from "./assets/brand/aeza-tyan-infra.webp";
import { BrandLogo, BrandPattern } from "./BrandLogo.jsx";
import { Brand, Icon } from "./Icons.jsx";
import {
  codewordError,
  matchError,
  passwordError,
  usernameError,
} from "./authRules.js";

const MODES = {
  login: "login",
  register: "register",
  forgot: "forgot",
  reset: "reset",
  done: "done",
};

const COPY = {
  [MODES.login]: {
    title: "С возвращением",
    lead: "Войдите, чтобы открыть аналитику клиентов.",
    submit: "Войти в панель",
  },
  [MODES.register]: {
    title: "Создать аккаунт",
    lead: "Имя и кодовое слово понадобятся, если забудете пароль.",
    submit: "Создать аккаунт",
  },
  [MODES.forgot]: {
    title: "Восстановление пароля",
    lead: "Введите логин и кодовое слово, которое указали при регистрации.",
    submit: "Проверить кодовое слово",
  },
  [MODES.reset]: {
    title: "Новый пароль",
    lead: "Не короче 10 символов, с буквами и цифрами.",
    submit: "Сохранить пароль",
  },
  [MODES.done]: {
    title: "Пароль изменён",
    lead: "Теперь войдите с новым паролем.",
    submit: "",
  },
};

const EMPTY_FORM = {
  username: "",
  password: "",
  confirm: "",
  firstName: "",
  lastName: "",
  codeword: "",
};

const HIDDEN_FIELD = {
  position: "absolute",
  width: 1,
  height: 1,
  opacity: 0,
  pointerEvents: "none",
};

function validate(mode, form) {
  if (mode === MODES.login) {
    return form.username.trim() && form.password ? "" : "Введите логин и пароль.";
  }
  if (mode === MODES.register) {
    if (!form.firstName.trim() || !form.lastName.trim()) return "Укажите имя и фамилию.";
    const username = form.username.trim().toLowerCase();
    return (
      usernameError(username) ||
      passwordError(form.password, username) ||
      matchError(form.password, form.confirm) ||
      codewordError(form.codeword, form.password)
    );
  }
  if (mode === MODES.forgot) {
    return form.username.trim() && form.codeword.trim()
      ? ""
      : "Введите логин и кодовое слово.";
  }
  if (mode === MODES.reset) {
    return (
      passwordError(form.password, form.username.trim()) ||
      matchError(form.password, form.confirm)
    );
  }
  return "";
}

export function Login({ onSession }) {
  const [mode, setMode] = useState(MODES.login);
  const [form, setForm] = useState({ ...EMPTY_FORM, username: "demo" });
  const [resetToken, setResetToken] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  // Bumped on every mode switch so a late response cannot overwrite the screen the user moved to.
  const requestRef = useRef(0);

  const copy = COPY[mode];
  const update = (field) => (event) => setForm({ ...form, [field]: event.target.value });

  function switchMode(nextMode) {
    requestRef.current += 1;
    setLoading(false);
    setMode(nextMode);
    setError("");
    setShowPassword(false);
    setForm((current) => ({
      ...EMPTY_FORM,
      username: nextMode === MODES.register ? "" : current.username,
    }));
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    const problem = validate(mode, form);
    if (problem) {
      setError(problem);
      return;
    }
    const token = requestRef.current;
    setLoading(true);
    try {
      if (mode === MODES.login) {
        // The session cookie is already set by the server, so a late reply still signs the user in.
        const result = await api.login(form.username.trim(), form.password);
        onSession(result.user);
      } else if (mode === MODES.register) {
        const result = await api.register({
          username: form.username.trim(),
          first_name: form.firstName.trim(),
          last_name: form.lastName.trim(),
          password: form.password,
          password_confirm: form.confirm,
          codeword: form.codeword,
        });
        onSession(result.user);
      } else if (mode === MODES.forgot) {
        const result = await api.verifyCodeword(form.username.trim(), form.codeword);
        if (token !== requestRef.current) return;
        setResetToken(result.reset_token);
        setForm((current) => ({ ...EMPTY_FORM, username: current.username }));
        setMode(MODES.reset);
      } else if (mode === MODES.reset) {
        await api.resetPassword({
          reset_token: resetToken,
          new_password: form.password,
          new_password_confirm: form.confirm,
        });
        if (token !== requestRef.current) return;
        setForm((current) => ({ ...EMPTY_FORM, username: current.username }));
        setMode(MODES.done);
      }
    } catch (requestError) {
      if (token !== requestRef.current) return;
      if (mode === MODES.reset && requestError.status === 400) {
        // The reset token expired or was used: start the recovery again from the codeword step.
        setResetToken("");
        setForm((current) => ({ ...EMPTY_FORM, username: current.username }));
        setMode(MODES.forgot);
        setError("Ссылка для сброса устарела. Введите логин и кодовое слово ещё раз.");
        return;
      }
      setError(requestError.message || "Не удалось выполнить запрос.");
    } finally {
      if (token === requestRef.current) setLoading(false);
    }
  }

  const passwordType = showPassword ? "text" : "password";
  const passwordToggle = (
    <button
      className="password-toggle"
      type="button"
      onClick={() => setShowPassword((value) => !value)}
    >
      {showPassword ? "Скрыть" : "Показать"}
    </button>
  );

  return (
    <main className="login-screen">
      <section className="login-intro">
        <BrandPattern tone="dark" className="login-pattern" />
        <div className="login-intro-top">
          <BrandLogo inverse />
        </div>
        <div className="login-intro-content">
          <h1>
            Риск непродления
            <br />
            <span>по каждому клиенту.</span>
          </h1>
          <p>Кто не продлит услуги и сколько выручки это может стоить.</p>
          <p className="login-slogan">Никакой магии. Только инфраструктура.</p>
        </div>
        <img
          className="login-mascot"
          src={mascot}
          alt=""
          width="360"
          height="541"
        />
        <div className="login-footer">
          <span>Демо-среда</span>
        </div>
      </section>

      <section className="login-panel">
        <form className="login-card" onSubmit={submit} noValidate>
          <div className="login-mobile-brand">
            <Brand />
          </div>
          <h2>{copy.title}</h2>
          <p className="login-lead">{copy.lead}</p>

          {mode === MODES.done ? (
            <button
              className="button button-primary login-submit"
              type="button"
              onClick={() => switchMode(MODES.login)}
            >
              Войти
              <Icon name="arrow" />
            </button>
          ) : (
            <>
              {mode === MODES.register && (
                <div className="field-row">
                  <div>
                    <label className="field-label" htmlFor="first-name">Имя</label>
                    <div className="input-wrap">
                      <input
                        id="first-name"
                        autoComplete="given-name"
                        maxLength={60}
                        value={form.firstName}
                        onChange={update("firstName")}
                      />
                    </div>
                  </div>
                  <div>
                    <label className="field-label" htmlFor="last-name">Фамилия</label>
                    <div className="input-wrap">
                      <input
                        id="last-name"
                        autoComplete="family-name"
                        maxLength={60}
                        value={form.lastName}
                        onChange={update("lastName")}
                      />
                    </div>
                  </div>
                </div>
              )}

              {(mode === MODES.login || mode === MODES.register || mode === MODES.forgot) && (
                <>
                  <label className="field-label" htmlFor="username">Логин</label>
                  <div className="input-wrap">
                    <input
                      id="username"
                      autoComplete="username"
                      value={form.username}
                      onChange={update("username")}
                      spellCheck={false}
                    />
                  </div>
                </>
              )}

              {(mode === MODES.login || mode === MODES.register || mode === MODES.reset) && (
                <>
                  <div className="password-label-row">
                    <label className="field-label" htmlFor="password">
                      {mode === MODES.reset ? "Новый пароль" : "Пароль"}
                    </label>
                    {mode === MODES.login && (
                      <button className="auth-link" type="button" onClick={() => switchMode(MODES.forgot)}>
                        Забыли пароль?
                      </button>
                    )}
                  </div>
                  <div className="input-wrap password-wrap">
                    <input
                      id="password"
                      type={passwordType}
                      autoComplete={mode === MODES.login ? "current-password" : "new-password"}
                      value={form.password}
                      onChange={update("password")}
                    />
                    {passwordToggle}
                  </div>
                </>
              )}

              {(mode === MODES.register || mode === MODES.reset) && (
                <>
                  <label className="field-label" htmlFor="confirm">Подтвердите пароль</label>
                  <div className="input-wrap password-wrap">
                    <input
                      id="confirm"
                      type={passwordType}
                      autoComplete="new-password"
                      value={form.confirm}
                      onChange={update("confirm")}
                    />
                  </div>
                </>
              )}

              {mode === MODES.reset && (
                // Lets password managers pair the new password with the account.
                <input
                  type="text"
                  name="username"
                  autoComplete="username"
                  value={form.username}
                  readOnly
                  tabIndex={-1}
                  aria-hidden="true"
                  style={HIDDEN_FIELD}
                />
              )}

              {(mode === MODES.register || mode === MODES.forgot) && (
                <>
                  <label className="field-label" htmlFor="codeword">Кодовое слово</label>
                  <div className="input-wrap">
                    <input
                      id="codeword"
                      autoComplete="off"
                      value={form.codeword}
                      onChange={update("codeword")}
                      aria-describedby="codeword-hint"
                    />
                  </div>
                  <span className="field-hint" id="codeword-hint">
                    {mode === MODES.register
                      ? "Запомните его: по нему восстанавливается пароль. От 6 до 64 символов, не только цифры."
                      : "Регистр букв не важен."}
                  </span>
                </>
              )}

              {error && (
                <div className="form-error" role="alert">
                  {error}
                </div>
              )}

              <button className="button button-primary login-submit" disabled={loading}>
                {loading ? "Подождите…" : copy.submit}
                <Icon name="arrow" />
              </button>

              <div className="auth-switch">
                {mode === MODES.login && (
                  <button className="auth-link" type="button" onClick={() => switchMode(MODES.register)}>
                    Нет аккаунта? Создать
                  </button>
                )}
                {mode === MODES.register && (
                  <button className="auth-link" type="button" onClick={() => switchMode(MODES.login)}>
                    Уже есть аккаунт? Войти
                  </button>
                )}
                {(mode === MODES.forgot || mode === MODES.reset) && (
                  <button className="auth-link" type="button" onClick={() => switchMode(MODES.login)}>
                    Вернуться ко входу
                  </button>
                )}
              </div>
            </>
          )}

          {mode === MODES.login && (
            <div className="demo-note">
              <span className="demo-note-icon">
                <Icon name="info" size={16} />
              </span>
              <span>
                <b>Локальный демо-вход</b>
                <small>Логин: demo · пароль указан в файле .env</small>
              </span>
            </div>
          )}
        </form>
        <div className="login-panel-bottom">
          <Icon name="shield" size={16} />
          Доступ к данным защищён индивидуальной сессией
        </div>
      </section>
    </main>
  );
}
