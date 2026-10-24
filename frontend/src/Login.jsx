import { useState } from "react";
import { Brand } from "./Icons.jsx";
import mascotLaptop from "./assets/mascot-laptop.webp";

export function Login({ onLogin }) {
  const [username, setUsername] = useState("demo");
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
      <form className="login-form" onSubmit={submit}>
        <header>
          <h1 className="h1">Вход</h1>
          <p>Панель защищена: данные клиентов видят только сотрудники</p>
        </header>
        <label className="field">
          <span>Логин</span>
          <input
            name="username"
            autoComplete="username"
            spellCheck={false}
            autoCapitalize="none"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />
        </label>
        <label className={`field${error ? " field-error" : ""}`}>
          <span>Пароль</span>
          <input
            name="password"
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
          {error && <small role="alert">{error}</small>}
        </label>
        <button
          type="button"
          className="link"
          style={{ alignSelf: "flex-start" }}
          onClick={() => setShowPassword((value) => !value)}
        >
          {showPassword ? "Скрыть пароль" : "Показать пароль"}
        </button>
        <button
          className="button button-primary button-wide"
          disabled={loading}
        >
          {loading ? "Проверяем…" : "Войти"}
        </button>
        <small>Локальный демо-вход: логин demo, пароль из файла .env</small>
      </form>
    </main>
  );
}
