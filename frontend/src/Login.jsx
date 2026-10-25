import { useEffect, useState } from "react";
import { api } from "./api.js";
import { matchError, passwordError, usernameError } from "./authRules.js";
import { Brand } from "./Icons.jsx";
import mascotLaptop from "./assets/mascot-laptop.webp";

const SSO_NOTICES = {
  failed: "Вход через SSO не выполнен. Попробуйте ещё раз.",
  denied: "Эта учётная запись не подключена к AEZA. Обратитесь к администратору.",
  unavailable: "Сервис SSO временно недоступен. Войдите по логину и паролю.",
};

// Колбэк SSO сообщает об ошибке в query string: читаем один раз и чистим URL.
function readSsoNotice() {
  const reason = new URLSearchParams(window.location.search).get("sso");
  if (!reason) return "";
  window.history.replaceState(null, "", window.location.pathname);
  return SSO_NOTICES[reason] || SSO_NOTICES.failed;
}

function Field({
  label,
  hint,
  error,
  name,
  type = "text",
  autoComplete,
  value,
  onChange,
  optional = false,
  ...rest
}) {
  const id = `field-${name}`;
  return (
    <label className={`field${error ? " field-error" : ""}`} htmlFor={id}>
      <span>
        {label}
        {optional && <em className="optional"> · необязательно</em>}
      </span>
      <input
        id={id}
        name={name}
        type={type}
        autoComplete={autoComplete}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={Boolean(error)}
        aria-describedby={error || hint ? `${id}-note` : undefined}
        {...rest}
      />
      {(error || hint) && (
        <small id={`${id}-note`} role={error ? "alert" : undefined}>
          {error || hint}
        </small>
      )}
    </label>
  );
}

function LoginForm({ onLogin, onMode, initialUsername, notice, methods }) {
  const [username, setUsername] = useState(initialUsername || "demo");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await onLogin(username.trim(), password);
    } catch (requestError) {
      setError(
        requestError.status === 401
          ? "Неверный логин или пароль. Проверьте раскладку и Caps Lock."
          : requestError.message || "Не удалось войти. Попробуйте ещё раз.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className="login-form" onSubmit={submit} noValidate>
      <header>
        <h1 className="h1">Вход</h1>
      </header>
      {notice && (
        <p className="form-notice" role="status">
          {notice}
        </p>
      )}
      <Field
        label="Логин"
        name="username"
        autoComplete="username"
        spellCheck={false}
        autoCapitalize="none"
        value={username}
        onChange={setUsername}
        required
      />
      <div className="field-with-action">
        <Field
          label="Пароль"
          name="password"
          type={showPassword ? "text" : "password"}
          autoComplete="current-password"
          value={password}
          onChange={setPassword}
          error={error}
          required
        />
        <button
          type="button"
          className="link field-action"
          onClick={() => onMode("reset", username)}
        >
          Забыли пароль?
        </button>
      </div>
      <button
        type="button"
        className="link"
        style={{ alignSelf: "flex-start" }}
        onClick={() => setShowPassword((value) => !value)}
      >
        {showPassword ? "Скрыть пароль" : "Показать пароль"}
      </button>
      <button className="button button-primary button-wide" disabled={loading}>
        {loading ? "Проверяем…" : "Войти"}
      </button>
      {methods.sso?.enabled && (
        <>
          <div className="auth-divider">
            <span>или</span>
          </div>
          <a
            className="button button-secondary button-wide"
            href="/api/v1/auth/oidc/login"
          >
            {methods.sso.label || "Войти через SSO"}
          </a>
        </>
      )}
    </form>
  );
}

function ResetForm({ onMode, initialUsername }) {
  const [step, setStep] = useState("verify");
  const [resetToken, setResetToken] = useState("");
  const [form, setForm] = useState({
    username: initialUsername === "demo" ? "" : initialUsername || "",
    codeword: "",
    new_password: "",
    new_password_confirm: "",
  });
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(false);
  const [serverError, setServerError] = useState("");
  const set = (key) => (value) =>
    setForm((current) => ({ ...current, [key]: value }));

  function focusFirst(next) {
    document.getElementById(`field-${Object.keys(next)[0]}`)?.focus();
  }

  async function verify(event) {
    event.preventDefault();
    setServerError("");
    const next = {};
    const login = usernameError(form.username.trim());
    if (login) next.username = login;
    if (!form.codeword.trim()) next.codeword = "Укажите кодовое слово";
    setErrors(next);
    if (Object.keys(next).length) return focusFirst(next);
    setLoading(true);
    try {
      const result = await api.verifyCodeword(form.username.trim(), form.codeword);
      setResetToken(result.reset_token);
      setStep("password");
    } catch (requestError) {
      setServerError(
        requestError.status === 401
          ? "Логин или кодовое слово не подходят. Проверьте раскладку."
          : requestError.message,
      );
    } finally {
      setLoading(false);
    }
  }

  async function reset(event) {
    event.preventDefault();
    setServerError("");
    const next = {};
    const password = passwordError(form.new_password, form.username.trim());
    if (password) next.new_password = password;
    const match = matchError(form.new_password, form.new_password_confirm);
    if (match) next.new_password_confirm = match;
    setErrors(next);
    if (Object.keys(next).length) return focusFirst(next);
    setLoading(true);
    try {
      await api.resetPassword({
        reset_token: resetToken,
        new_password: form.new_password,
        new_password_confirm: form.new_password_confirm,
      });
      onMode("login", form.username.trim(), "Пароль изменён. Войдите с новым паролем.");
    } catch (requestError) {
      if (requestError.status === 400) {
        setStep("verify");
        setResetToken("");
        setServerError("Ссылка для сброса устарела. Введите кодовое слово ещё раз.");
      } else setServerError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className="login-form" onSubmit={step === "verify" ? verify : reset} noValidate>
      <header>
        <h1 className="h1">Сброс пароля</h1>
        <p>
          {step === "verify"
            ? "Введите логин и кодовое слово, которое указывали при регистрации"
            : "Задайте новый пароль. Ссылка для сброса действует 10 минут."}
        </p>
      </header>
      {step === "verify" ? (
        <>
          <Field
            label="Логин"
            name="username"
            autoComplete="username"
            spellCheck={false}
            autoCapitalize="none"
            value={form.username}
            onChange={set("username")}
            error={errors.username}
          />
          <Field
            label="Кодовое слово"
            name="codeword"
            autoComplete="off"
            spellCheck={false}
            value={form.codeword}
            onChange={set("codeword")}
            error={errors.codeword}
          />
        </>
      ) : (
        <div className="fields">
          <Field
            label="Новый пароль"
            name="new_password"
            type="password"
            autoComplete="new-password"
            value={form.new_password}
            onChange={set("new_password")}
            error={errors.new_password}
          />
          <Field
            label="Повторите пароль"
            name="new_password_confirm"
            type="password"
            autoComplete="new-password"
            value={form.new_password_confirm}
            onChange={set("new_password_confirm")}
            error={errors.new_password_confirm}
          />
        </div>
      )}
      {serverError && (
        <p className="inline-error" role="alert">
          {serverError}
        </p>
      )}
      <button className="button button-primary button-wide" disabled={loading}>
        {loading
          ? "Подождите…"
          : step === "verify"
            ? "Продолжить"
            : "Сменить пароль"}
      </button>
      <p className="form-switch">
        Вспомнили?{" "}
        <button type="button" className="link" onClick={() => onMode("login")}>
          Вернуться ко входу
        </button>
      </p>
    </form>
  );
}

export function Login({ onLogin }) {
  const [view, setView] = useState({ mode: "login", username: "", notice: "" });
  const [methods, setMethods] = useState({
    password: true,
    sso: { enabled: false, label: "" },
  });
  const [ssoNotice] = useState(readSsoNotice);
  useEffect(() => {
    let active = true;
    api
      .authMethods()
      .then((available) => {
        if (active) setMethods(available);
      })
      .catch(() => {
        /* Без списка форма пароля всё равно работает. */
      });
    return () => {
      active = false;
    };
  }, []);
  const onMode = (mode, username = "", notice = "") =>
    setView({ mode, username, notice });

  return (
    <main className="login">
      <section className="login-brand" aria-hidden="true">
        <Brand inverse />
        <div className="login-copy">
          <p className="display">
            Никакой магии.
            <br />
            Только цифры.
          </p>
          <p>
            Покажем, кто из клиентов может не продлить, почему и сколько денег
            на кону.
          </p>
        </div>
        <div className="login-line" />
        <div className="stripes">
          <i />
          <i />
          <i />
        </div>
        <img
          className="login-mascot"
          src={mascotLaptop}
          width="760"
          height="931"
          alt=""
          fetchPriority="high"
        />
      </section>
      <div className="login-side">
        {view.mode === "reset" ? (
          <ResetForm onMode={onMode} initialUsername={view.username} />
        ) : (
          <LoginForm
            key={view.username + view.notice}
            onLogin={onLogin}
            onMode={onMode}
            initialUsername={view.username}
            notice={view.notice || ssoNotice}
            methods={methods}
          />
        )}
      </div>
    </main>
  );
}
