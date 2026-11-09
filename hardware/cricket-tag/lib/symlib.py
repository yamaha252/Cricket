"""Общие функции для генераторов библиотеки и схемы cricket: разбор
s-выражений KiCad и замена одного символа в файле .kicad_sym."""

import os


def sexpr_end(text, start):
    """Индекс за концом s-выражения, которое начинается с '(' в позиции start."""
    depth, i, in_str = 0, start, False
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced s-expression")


def parse(text):
    """Разбор s-выражения в вложенные списки; строки остаются в кавычках."""
    out, stack, i, n = [], [], 0, len(text)
    cur = out
    while i < n:
        ch = text[i]
        if ch == "(":
            stack.append(cur)
            new = []
            cur.append(new)
            cur = new
            i += 1
        elif ch == ")":
            cur = stack.pop()
            i += 1
        elif ch.isspace():
            i += 1
        elif ch == '"':
            j = i + 1
            while text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            cur.append(text[i:j + 1])
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in "()":
                j += 1
            cur.append(text[i:j])
            i = j
    return out[0]


def unq(s):
    return s[1:-1] if s.startswith('"') else s


def find_symbol_text(lib_text, name):
    """Исходный текст верхнеуровневого символа name из библиотеки."""
    # верхний уровень библиотеки KiCad — отступ ровно в один таб
    key = f'\n\t(symbol "{name}"'
    s = lib_text.find(key)
    if s < 0:
        raise KeyError(name)
    s += 2
    return lib_text[s:sexpr_end(lib_text, s)]


def upsert_symbol(path, name, lib_text):
    """Записывает символ name из lib_text в библиотеку path, не трогая другие."""
    block = find_symbol_text(lib_text, name)
    if not os.path.exists(path):
        with open(path, "w") as fh:
            fh.write(lib_text)
        return
    with open(path) as fh:
        text = fh.read()
    try:
        old = find_symbol_text(text, name)
        text = text.replace(old, block, 1)
    except KeyError:
        e = text.rstrip().rindex(")")
        text = text[:e] + "\t" + block + "\n" + text[e:]
    with open(path, "w") as fh:
        fh.write(text)
