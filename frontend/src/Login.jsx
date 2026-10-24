import { useState } from "react";
import { api } from "./api.js";
import { Brand } from "./Icons.jsx";
import mascotLaptop from "./assets/mascot-laptop.webp";

const USERNAME_RE = /^[A-Za-z0-9._@-]{3,64}$/;

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

function LoginForm({ onLogin, onMode, initialUsername, notice }) {
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
        <p>Панель защищена: данные клиентов видят только сотрудники</p>
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
      <p className="form-switch">
        Нет аккаунта?{" "}
        <button
          type="button"
          className="link"
          onClick={() => onMode("register")}
        >
          Зарегистрироваться
        </button>
      </p>
    </form>
  );
}

function RegisterForm({ onRegistered, onMode }) {
  const [form, setForm] = useState({
    last_name: "",
    first_name: "",
    middle_name: "",
    username: "",
    password: "",
    password_confirm: "",
    codeword: "",
  });
  const [errors, setErrors] = useState({});
  const [touched, setTouched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [serverError, setServerError] = useState("");
  const set = (key) => (value) =>
    setForm((current) => ({ ...current, [key]: value }));

  function validate(values) {
    const next = {};
    if (!values.last_name.trim()) next.last_name = "Укажите фамилию";
    if (!values.first_name.trim()) next.first_name = "Укажите имя";
    if (!USERNAME_RE.test(values.username.trim()))
      next.username = "От 3 символов: латиница, цифры и . _ @ -";
    if (values.password.length < 8) next.password = "Пароль от 8 символов";
    if (values.password_confirm !== values.password)
      next.password_confirm = "Пароли не совпадают";
    if (values.codeword.trim().length < 4)
      next.codeword = "Кодовое слово от 4 символов";
    else if (
      values.codeword.trim().toLowerCase() === values.password.toLowerCase()
    )
      next.codeword = "Кодовое слово не должно совпадать с паролем";
    return next;
  }

  async function submit(event) {
    event.preventDefault();
    setTouched(true);
    setServerError("");
    const next = validate(form);
    setErrors(next);
    if (Object.keys(next).length) {
      document.getElementById(`field-${Object.keys(next)[0]}`)?.focus();
      return;
    }
    setLoading(true);
    try {
      const result = await api.register({
        ...form,
        middle_name: form.middle_name.trim() || null,
      });
      onRegistered(result.user);
    } catch (requestError) {
      if (requestError.status === 409) {
        setErrors({ username: requestError.message });
        document.getElementById("field-username")?.focus();
      } else setServerError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  const err = (key) => (touched ? errors[key] : "");
  const onChange = (key) => (value) => {
    set(key)(value);
    if (touched) setErrors(validate({ ...form, [key]: value }));
  };

  return (
    <form className="login-form" onSubmit={submit} noValidate>
      <header>
        <h1 className="h1">Регистрация</h1>
        <p>Доступ к панели для сотрудников Aéza</p>
      </header>
      <div className="fields">
        <Field
          label="Фамилия"
          name="last_name"
          autoComplete="family-name"
          value={form.last_name}
          onChange={onChange("last_name")}
          error={err("last_name")}
        />
        <Field
          label="Имя"
          name="first_name"
          autoComplete="given-name"
          value={form.first_name}
          onChange={onChange("first_name")}
          error={err("first_name")}
        />
      </div>
      <Field
        label="Отчество"
        optional
        name="middle_name"
        autoComplete="additional-name"
        value={form.middle_name}
        onChange={onChange("middle_name")}
      />
      <Field
        label="Логин"
        name="username"
        autoComplete="username"
        spellCheck={false}
        autoCapitalize="none"
        hint="Латиница, цифры и . _ @ -, можно рабочий email"
        value={form.username}
        onChange={onChange("username")}
        error={err("username")}
      />
      <div className="fields">
        <Field
          label="Пароль"
          name="password"
          type="password"
          autoComplete="new-password"
          value={form.password}
          onChange={onChange("password")}
          error={err("password")}
        />
        <Field
          label="Повторите пароль"
          name="password_confirm"
          type="password"
          autoComplete="new-password"
          value={form.password_confirm}
          onChange={onChange("password_confirm")}
          error={err("password_confirm")}
        />
      </div>
      <Field
        label="Кодовое слово"
        name="codeword"
        autoComplete="off"
        spellCheck={false}
        hint="Спросим его, если забудете пароль. Регистр не важен"
        value={form.codeword}
        onChange={onChange("codeword")}
        error={err("codeword")}
      />
      {serverError && (
        <p className="inline-error" role="alert">
          {serverError}
        </p>
      )}
      <button className="button button-primary button-wide" disabled={loading}>
        {loading ? "Создаём аккаунт…" : "Зарегистрироваться"}
      </button>
      <p className="form-switch">
        Уже есть аккаунт?{" "}
        <button type="button" className="link" onClick={() => onMode("login")}>
          Войти
        </button>
      </p>
    </form>
  );
}

function ResetForm({ onMode, initialUsername }) {
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

  async function submit(event) {
    event.preventDefault();
    setServerError("");
    const next = {};
    if (!form.username.trim()) next.username = "Укажите логин";
    if (!form.codeword.trim()) next.codeword = "Укажите кодовое слово";
    if (form.new_password.length < 8)
      next.new_password = "Пароль от 8 символов";
    if (form.new_password_confirm !== form.new_password)
      next.new_password_confirm = "Пароли не совпадают";
    setErrors(next);
    if (Object.keys(next).length) {
      document.getElementById(`field-${Object.keys(next)[0]}`)?.focus();
      return;
    }
    setLoading(true);
    try {
      await api.resetPassword({ ...form, username: form.username.trim() });
      onMode(
        "login",
        form.username.trim(),
        "Пароль изменён. Войдите с новым паролем.",
      );
    } catch (requestError) {
      setServerError(
        requestError.status === 400
          ? "Логин или кодовое слово не подходят. Проверьте раскладку."
          : requestError.message,
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className="login-form" onSubmit={submit} noValidate>
      <header>
        <h1 className="h1">Сброс пароля</h1>
        <p>Введите логин и кодовое слово, которое указывали при регистрации</p>
      </header>
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
      {serverError && (
        <p className="inline-error" role="alert">
          {serverError}
        </p>
      )}
      <button className="button button-primary button-wide" disabled={loading}>
        {loading ? "Меняем пароль…" : "Сменить пароль"}
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

export function Login({ onLogin, onRegistered }) {
  const [view, setView] = useState({ mode: "login", username: "", notice: "" });
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
        {view.mode === "register" ? (
          <RegisterForm onRegistered={onRegistered} onMode={onMode} />
        ) : view.mode === "reset" ? (
          <ResetForm onMode={onMode} initialUsername={view.username} />
        ) : (
          <LoginForm
            key={view.username + view.notice}
            onLogin={onLogin}
            onMode={onMode}
            initialUsername={view.username}
            notice={view.notice}
          />
        )}
      </div>
    </main>
  );
}
