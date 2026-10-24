import { Icon } from "./Icons.jsx";
import { CustomerTable, PageHeader } from "./Shared.jsx";
import { riskText } from "./format.js";

export function CustomersPage({
  customers,
  total,
  filters,
  setFilters,
  onSelectCustomer,
  onNavigate,
  onSort,
  pageNumber,
  setPageNumber,
}) {
  const pages = Math.max(1, Math.ceil(total / 8));
  const shown = customers.slice((pageNumber - 1) * 8, pageNumber * 8);
  const currentFilterLabel = filters.risk_level
    ? riskText[filters.risk_level]
    : "Все статусы";
  return (
    <>
      <PageHeader
        eyebrow="КЛИЕНТСКАЯ БАЗА"
        title="Клиенты"
        description="Найдите аккаунт и откройте подробные сигналы риска."
        onMenu={onNavigate.menu}
        action={
          <span className="total-chip">
            <span className="status-indicator" />
            {total} клиентов
          </span>
        }
      />
      <section className="panel clients-panel">
        <div className="client-toolbar">
          <label className="search-box">
            <Icon name="search" size={18} />
            <input
              value={filters.q}
              onChange={(event) => {
                setPageNumber(1);
                setFilters({ ...filters, q: event.target.value });
              }}
              placeholder="Поиск по ID или email"
              aria-label="Поиск по ID или email"
            />
            <kbd>/</kbd>
          </label>
          <label className="select-box">
            <span className="select-label">Риск</span>
            <select
              value={filters.risk_level}
              onChange={(event) => {
                setPageNumber(1);
                setFilters({ ...filters, risk_level: event.target.value });
              }}
              aria-label="Фильтр по риску"
            >
              <option value="">Все статусы</option>
              <option value="high">Высокий риск</option>
              <option value="medium">Средний риск</option>
              <option value="low">Низкий риск</option>
              <option value="unscored">Нет оценки</option>
            </select>
            <Icon name="chevron" size={15} />
          </label>
          <label className="select-box sort-select">
            <span className="select-label">Сортировка</span>
            <select
              value={`${filters.sort_by}:${filters.order}`}
              onChange={(event) => {
                const [sort_by, order] = event.target.value.split(":");
                setPageNumber(1);
                setFilters({ ...filters, sort_by, order });
              }}
              aria-label="Сортировка клиентов"
            >
              <option value="risk_score:desc">По риску</option>
              <option value="id:asc">По ID</option>
              <option value="email:asc">По email</option>
              <option value="balance:desc">По балансу</option>
              <option value="total_replenished:desc">По пополнениям</option>
              <option value="potential_loss:desc">По сумме риска</option>
            </select>
            <Icon name="chevron" size={15} />
          </label>
          <span className="toolbar-count">{currentFilterLabel}</span>
        </div>
        <CustomerTable
          customers={shown}
          onSelect={onSelectCustomer}
          sortBy={filters.sort_by}
          order={filters.order}
          onSort={onSort}
          includeAll
        />
        <div className="table-pagination">
          <span>
            Показано{" "}
            <b>
              {total ? Math.min((pageNumber - 1) * 8 + 1, total) : 0}–
              {Math.min(pageNumber * 8, total)}
            </b>{" "}
            из <b>{total}</b>
          </span>
          <div>
            <button
              className="pagination-button"
              aria-label="Предыдущая страница"
              disabled={pageNumber <= 1}
              onClick={() => setPageNumber((page) => page - 1)}
            >
              ‹
            </button>
            <span className="pagination-current">
              {pageNumber} <i>/</i> {pages}
            </span>
            <button
              className="pagination-button"
              aria-label="Следующая страница"
              disabled={pageNumber >= pages}
              onClick={() => setPageNumber((page) => page + 1)}
            >
              ›
            </button>
          </div>
        </div>
      </section>
      <div className="client-bottom-note">
        <Icon name="info" size={16} />
        <span>
          Кликните по строке, чтобы увидеть услуги, историю транзакций и расчёт
          оценки.
        </span>
      </div>
    </>
  );
}
