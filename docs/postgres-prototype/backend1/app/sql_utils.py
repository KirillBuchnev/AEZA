import re
def split_statements(sql: str) -> list[str]:
    out, buf, i, n = [], [], 0, len(sql)
    in_single = in_double = False; dollar_tag = None
    while i < n:
        ch = sql[i]; two = sql[i:i + 2]
        if dollar_tag is None and not in_single and not in_double and ch == "$":
            j = sql.find("$", i + 1)
            if j != -1:
                tag = sql[i:j + 1]
                if re.fullmatch(r"\$[A-Za-z_]*\$", tag):
                    dollar_tag = tag; buf.append(tag); i = j + 1; continue
        if dollar_tag is not None:
            if sql.startswith(dollar_tag, i): buf.append(dollar_tag); i += len(dollar_tag); dollar_tag = None; continue
            buf.append(ch); i += 1; continue
        if not in_double and ch == "'": in_single = not in_single
        elif not in_single and ch == '"': in_double = not in_double
        elif ch == "-" and two == "--" and not in_single and not in_double:
            j = sql.find("\n", i)
            if j == -1: buf.append(sql[i:]); break
            buf.append(sql[i:j + 1]); i = j + 1; continue
        if ch == ";" and not in_single and not in_double:
            out.append("".join(buf)); buf = []; i += 1; continue
        buf.append(ch); i += 1
    tail = "".join(buf).strip()
    if tail: out.append(tail)
    return out