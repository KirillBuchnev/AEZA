import { useEffect, useState } from "react";
import { api } from "./api.js";
import { usernameError } from "./authRules.js";
import { CardHead, PageHead } from "./Shared.jsx";

const ROLE_LABELS = { analyst: "Аналитик", admin: "Администратор" };
const EMPTY_FORM = {
  username: "",
  last_name: "",
  first_name: "",
  middle_name: "",
  role: "analyst",
};

function RoleSelect({ value, disabled, onChange }) {
  return (
    <div className="select">
      <select
        aria-label="Роль"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {Object.entries(ROLE_LABELS).map(([role, label]) => (
          <option key={role} value={role}>
            {label}
          </option>
        ))}
      </select>
    </div>
  );
}

export function AdminPage({ currentUser, onToast }) {
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);

  function reload() {
    return api
      .adminUsers()
      .then((payload) => setUsers(payload.items))
      .catch((requestError) =>
        onToast({ kind: "error", message: requestError.message }),
      );
  }

  // Список загружаем один раз, когда администратор открывает страницу.
  useEffect(() => {
    reload();
  }, []);

  async function create(event) {
    event.preventDefault();
    const login = form.username.trim();
    const problem = usernameError(login);
    if (problem) return setFormError(problem);
    if (!form.last_name.trim() || !form.first_name.trim())
      return setFormError("Укажите фамилию и имя.");
    setFormError("");
    setSaving(true);
    try {
      await api.adminCreateUser({
        username: login,
        last_name: form.last_name.trim(),
        first_name: form.first_name.trim(),
        middle_name: form.middle_name.trim() || null,
        role: form.role,
      });
      setForm(EMPTY_FORM);
      onToast({ kind: "success", message: `Сотрудник ${login} добавлен. Он войдёт через SSO.` });
      await reload();
    } catch (requestError) {
      setFormError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  async function update(username, changes, doneText) {
    try {
      await api.adminUpdateUser(username, changes);
      onToast({ kind: "success", message: doneText });
      await reload();
    } catch (requestError) {
      onToast({ kind: "error", message: requestError.message });
    }
  }

  const setField = (key) => (event) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  return (
    <>
      <PageHead
        title="Пользователи"
        description="Сотрудники входят через корпоративный SSO. Администратор заводит их здесь и выдаёт роль. Незнакомый логин в SSO войти не может."
      />

      <section className="card">
        <CardHead
          title="Новый сотрудник"
          description="Логин должен совпадать с логином в корпоративном SSO."
        />
        <form className="fields" onSubmit={create} noValidate>
          <label className="field">
            <span>Логин в SSO</span>
            <input
              name="username"
              autoComplete="off"
              spellCheck={false}
              value={form.username}
              onChange={setField("username")}
            />
          </label>
          <label className="field">
            <span>Фамилия</span>
            <input name="last_name" value={form.last_name} onChange={setField("last_name")} />
          </label>
          <label className="field">
            <span>Имя</span>
            <input name="first_name" value={form.first_name} onChange={setField("first_name")} />
          </label>
          <label className="field">
            <span>Отчество</span>
            <input name="middle_name" value={form.middle_name} onChange={setField("middle_name")} />
          </label>
          <div className="field">
            <span>Роль</span>
            <RoleSelect
              value={form.role}
              onChange={(role) => setForm((current) => ({ ...current, role }))}
            />
          </div>
          {formError && (
            <p className="form-error" role="alert">
              {formError}
            </p>
          )}
          <button className="button button-primary" disabled={saving}>
            {saving ? "Добавляем…" : "Завести сотрудника"}
          </button>
        </form>
      </section>

      <section className="table-card">
        <div className="table-scroll">
          <table className="ctable">
            <thead>
              <tr>
                <th>Логин</th>
                <th>ФИО</th>
                <th>Роль</th>
                <th>Вход</th>
                <th>Статус</th>
                <th aria-label="Действия" />
              </tr>
            </thead>
            <tbody>
              {users.map((user) => {
                const isSelf = user.username === currentUser?.username;
                return (
                  <tr key={user.username}>
                    <td>{user.username}</td>
                    <td>{user.full_name}</td>
                    <td>
                      <RoleSelect
                        value={user.role}
                        disabled={isSelf}
                        onChange={(role) =>
                          update(user.username, { role }, `Роль ${user.username}: ${ROLE_LABELS[role]}.`)
                        }
                      />
                    </td>
                    <td>{user.has_password ? "Аварийный пароль" : "SSO"}</td>
                    <td>{user.active ? "Активен" : "Заблокирован"}</td>
                    <td>
                      <button
                        type="button"
                        className="button button-secondary"
                        disabled={isSelf}
                        title={isSelf ? "Нельзя заблокировать себя" : undefined}
                        onClick={() =>
                          update(
                            user.username,
                            { active: !user.active },
                            user.active
                              ? `${user.username} заблокирован, сессии закрыты.`
                              : `${user.username} снова активен.`,
                          )
                        }
                      >
                        {user.active ? "Заблокировать" : "Разблокировать"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
