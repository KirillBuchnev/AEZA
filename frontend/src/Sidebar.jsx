import { pageHref } from "./routes.js";
import { Brand, Icon } from "./Icons.jsx";
import mascotPeek from "./assets/mascot-peek.webp";

const groups = [
  {
    label: "Анализ",
    items: [
      { id: "overview", label: "Обзор" },
      { id: "customers", label: "Клиенты", countKey: "customers_total" },
    ],
  },
  {
    label: "Управление",
    items: [
      { id: "model", label: "Модель риска" },
      { id: "source", label: "Источник данных" },
    ],
  },
];

export function Sidebar({
  page,
  setPage,
  user,
  summary,
  onLogout,
  mobileOpen,
  setMobileOpen,
}) {
  const activePage = page === "customer" ? "customers" : page;
  return (
    <>
      {mobileOpen && (
        <button
          className="sidebar-scrim"
          aria-label="Закрыть меню"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside className={`sidebar${mobileOpen ? " sidebar-open" : ""}`}>
        <div className="sidebar-logo">
          <Brand inverse />
        </div>
        <nav aria-label="Основная навигация">
          {groups.map((group, index) => (
            <div key={group.label}>
              {index > 0 && <div className="nav-gap" />}
              <div className="nav-group">{group.label}</div>
              {group.items.map((item) => (
                <a
                  key={item.id}
                  href={pageHref(item.id)}
                  className={`nav-item${activePage === item.id ? " nav-item-active" : ""}`}
                  aria-current={activePage === item.id ? "page" : undefined}
                  onClick={(event) => {
                    if (event.metaKey || event.ctrlKey || event.shiftKey)
                      return;
                    event.preventDefault();
                    setPage(item.id);
                    setMobileOpen(false);
                  }}
                >
                  <span>{item.label}</span>
                  {item.countKey && summary?.[item.countKey] != null && (
                    <small>{summary[item.countKey]}</small>
                  )}
                </a>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-mascot" aria-hidden="true">
          <img src={mascotPeek} alt="" width="110" height="91" />
        </div>
        <div className="sidebar-user">
          <span className="avatar">
            {(user?.full_name || user?.username || "A")
              .slice(0, 1)
              .toUpperCase()}
          </span>
          <span className="sidebar-user-text">
            <b>{user?.full_name || user?.username || "Аналитик"}</b>
            <small>Маркетинг</small>
          </span>
          <button
            className="icon-button"
            aria-label="Выйти"
            title="Выйти"
            onClick={onLogout}
          >
            <Icon name="logout" size={18} />
          </button>
        </div>
      </aside>
    </>
  );
}
