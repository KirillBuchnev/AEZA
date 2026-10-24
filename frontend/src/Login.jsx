import { useState } from "react";
import { Brand, Icon } from "./Icons.jsx";

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
        requestError.message || "Не удалось войти. Проверьте логин и пароль.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-screen">
      <section className="login-intro">
        <div className="login-intro-top">
          <Brand />
          <span className="login-version">RETENTION ANALYTICS</span>
        </div>
        <div className="login-intro-content">
          <div className="eyebrow eyebrow-light">
            <span className="live-dot" />
            ПАНЕЛЬ АНАЛИТИКА
          </div>
          <h1>
            Сохраните важные
            <br />
            <span>клиентские связи.</span>
          </h1>
          <p>
            Понятно показываем, кому скоро понадобится внимание и какая выручка
            зависит от продления.
          </p>
          <div className="login-points">
            <div>
              <span className="point-icon">
                <Icon name="pulse" />
              </span>
              <span>
                <b>Риск с объяснением</b>
                <small>Каждая оценка опирается на конкретные сигналы</small>
              </span>
            </div>
            <div>
              <span className="point-icon">
                <Icon name="wallet" />
              </span>
              <span>
                <b>Выручка под контролем</b>
                <small>Видно, сколько денег может быть потеряно</small>
              </span>
            </div>
          </div>
        </div>
        <div className="login-footer">
          <span>AEZA RETENTION CONSOLE</span>
          <span>Демо-среда</span>
        </div>
        <div className="login-orbit login-orbit-one" />
        <div className="login-orbit login-orbit-two" />
      </section>
      <section className="login-panel">
        <form className="login-card" onSubmit={submit}>
          <div className="login-mobile-brand">
            <Brand />
          </div>
          <span className="eyebrow">РАБОЧЕЕ ПРОСТРАНСТВО</span>
          <h2>С возвращением</h2>
          <p className="login-lead">
            Войдите, чтобы открыть аналитику клиентов.
          </p>
          <label className="field-label" htmlFor="username">
            Логин
          </label>
          <div className="input-wrap">
            <input
              id="username"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
            />
          </div>
          <div className="password-label-row">
            <label className="field-label" htmlFor="password">
              Пароль
            </label>
            <span className="login-hint">Пароль не сохраняется в браузере</span>
          </div>
          <div className="input-wrap password-wrap">
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
            <button
              className="password-toggle"
              type="button"
              onClick={() => setShowPassword((value) => !value)}
            >
              {showPassword ? "Скрыть" : "Показать"}
            </button>
          </div>
          {error && (
            <div className="form-error" role="alert">
              {error}
            </div>
          )}
          <button
            className="button button-primary login-submit"
            disabled={loading}
          >
            {loading ? "Проверяем данные…" : "Войти в панель"}
            <Icon name="arrow" />
          </button>
          <div className="demo-note">
            <span className="demo-note-icon">
              <Icon name="info" size={16} />
            </span>
            <span>
              <b>Локальный демо-вход</b>
              <small>Логин: demo · пароль указан в файле .env</small>
            </span>
          </div>
        </form>
        <div className="login-panel-bottom">
          Доступ к данным защищён индивидуальной сессией
        </div>
      </section>
    </main>
  );
}
