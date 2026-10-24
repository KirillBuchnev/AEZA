import { Icon } from "./Icons.jsx";
import {
  CustomerTable,
  Empty,
  PageHead,
  Segments,
  SkeletonRows,
} from "./Shared.jsx";
import { riskText } from "./format.js";

const PAGE_SIZE = 10;

export function CustomersPage({
  customers,
  total,
  summary,
  filters,
  setFilters,
  loading,
  onSelectCustomer,
  onSort,
  onExport,
  pageNumber,
  setPageNumber,
}) {
  const pages = Math.max(1, Math.ceil(customers.length / PAGE_SIZE));
  const shown = customers.slice(
    (pageNumber - 1) * PAGE_SIZE,
    pageNumber * PAGE_SIZE,
  );
  const counts = summary?.risk_counts || {};
  const first = customers.length ? (pageNumber - 1) * PAGE_SIZE + 1 : 0;

  return (
    <>
      <PageHead
        title="Клиенты"
        description={`${summary?.customers_total ?? total} клиентов · рейтинг пересчитывается сам при новых данных или коэффициентах`}
      >
        <label className="search">
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
        </label>
        <button className="button button-secondary" onClick={onExport}>
          <Icon name="download" size={16} />
          Экспорт CSV
        </button>
      </PageHead>

      <div className="filters">
        <Segments
          label="Фильтр по уровню риска"
          value={filters.risk_level}
          onChange={(value) => {
            setPageNumber(1);
            setFilters({ ...filters, risk_level: value });
          }}
          items={[
            { value: "", label: "Все", count: summary?.customers_total },
            ...["high", "medium", "low", "unscored"].map((key) => ({
              value: key,
              label: riskText[key],
              count: counts[key] ?? 0,
            })),
          ]}
        />
      </div>

      <section className="table-card">
        {loading && !customers.length ? (
          <SkeletonRows />
        ) : customers.length ? (
          <CustomerTable
            customers={shown}
            sortBy={filters.sort_by}
            order={filters.order}
            onSort={onSort}
            onSelect={onSelectCustomer}
          />
        ) : (
          <Empty
            title="Никого не нашли"
            action={
              <button
                className="button button-secondary"
                onClick={() =>
                  setFilters({ ...filters, q: "", risk_level: "" })
                }
              >
                Сбросить поиск и фильтр
              </button>
            }
          >
            Измените запрос или уровень риска — список обновится сразу.
          </Empty>
        )}
        <div className="table-foot">
          <span>
            {first}–{Math.min(pageNumber * PAGE_SIZE, customers.length)} из{" "}
            {customers.length}
          </span>
          <button
            className="icon-button flip"
            aria-label="Предыдущая страница"
            disabled={pageNumber <= 1}
            onClick={() => setPageNumber((page) => page - 1)}
          >
            <Icon name="right" size={16} />
          </button>
          <span className="small">
            {pageNumber} / {pages}
          </span>
          <button
            className="icon-button"
            aria-label="Следующая страница"
            disabled={pageNumber >= pages}
            onClick={() => setPageNumber((page) => page + 1)}
          >
            <Icon name="right" size={16} />
          </button>
        </div>
      </section>
    </>
  );
}
