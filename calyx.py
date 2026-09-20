#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Calyx - un langage simple, lisible et modulaire.

Un seul fichier, aucune dépendance (Python 3.8+ suffit).
Fonctionne sous Linux, macOS et Windows : seuls les chemins de fichiers changent.

Usage :
    calyx script.cx [arguments]     exécuter un programme
    calyx                           console interactive (REPL)
    calyx install module.cx         installer un module pour tous les projets
    calyx modules                   lister les modules installés
    calyx --help
"""
import sys
import os
import re
import time
import math
import json
import random
import threading
import functools
import difflib
import datetime
import platform
import shutil
import subprocess
import mimetypes

VERSION = "1.0.3"
EXT = ".cx"


# ======================================================================
#  CHEMINS  (la seule chose qui change entre Linux et Windows)
# ======================================================================

def modules_dir():
    """Dossier universel des modules, partagé par tous les projets."""
    custom = os.environ.get("CALYX_MODULES")
    if custom:
        return custom
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        return os.path.join(base, "Calyx", "modules")
    return os.path.join(os.path.expanduser("~"), ".calyx", "modules")


def read_source(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


# ======================================================================
#  ERREURS ET CONTRÔLE DE FLUX
# ======================================================================

class CalyxError(Exception):
    def __init__(self, msg, line=None, value=None):
        Exception.__init__(self, msg)
        self.msg = msg
        self.line = line
        self.value = msg if value is None else value
        self.file = None


class ControlFlow(BaseException):
    pass


class ReturnEx(ControlFlow):
    def __init__(self, value=None):
        self.value = value


class BreakEx(ControlFlow):
    pass


class ContinueEx(ControlFlow):
    pass


# ======================================================================
#  ANALYSE LEXICALE
# ======================================================================

KEYWORDS = {
    "let", "const", "fn", "if", "else", "while", "for", "in", "return",
    "break", "continue", "use", "as", "class", "extends", "try", "catch",
    "throw", "true", "false", "null", "and", "or", "not",
}
TWO_OPS = {"==", "!=", "<=", ">=", "&&", "||", "+=", "-=", "*=", "/=", "%=", "**"}
ONE_OPS = set("+-*/%<>=!(){}[],.;:")
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", '"': '"', "'": "'", "$": "$"}


def tokenize(src, line=1):
    toks = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        if c == "/" and src[i + 1:i + 2] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c == "/" and src[i + 1:i + 2] == "*":
            j = src.find("*/", i + 2)
            if j < 0:
                raise CalyxError("Commentaire /* jamais fermé (il manque */)", line)
            line += src.count("\n", i, j)
            i = j + 2
            continue
        if c.isdigit():
            j = i
            while j < n and src[j].isdigit():
                j += 1
            if j < n and src[j] == "." and src[j + 1:j + 2].isdigit():
                j += 1
                while j < n and src[j].isdigit():
                    j += 1
                toks.append(("num", float(src[i:j]), line))
            else:
                toks.append(("num", int(src[i:j]), line))
            i = j
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            w = src[i:j]
            toks.append(("kw" if w in KEYWORDS else "id", w, line))
            i = j
            continue
        if c == "#":
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] in "_/-."):
                j += 1
            toks.append(("path", src[i:j], line))
            i = j
            continue
        if c in "\"'":
            q = c
            interp = q == '"'
            start_line = line
            parts, buf = [], []
            i += 1
            while True:
                if i >= n:
                    raise CalyxError("Texte jamais fermé (guillemet manquant)", start_line)
                ch = src[i]
                if ch == q:
                    i += 1
                    break
                if ch == "\\" and i + 1 < n:
                    nxt = src[i + 1]
                    buf.append(ESCAPES.get(nxt, "\\" + nxt))
                    i += 2
                    continue
                if interp and ch == "$" and src[i + 1:i + 2] == "{":
                    depth, j = 1, i + 2
                    while j < n and depth > 0:
                        if src[j] == "{":
                            depth += 1
                        elif src[j] == "}":
                            depth -= 1
                        j += 1
                    if depth != 0:
                        raise CalyxError("Interpolation ${...} jamais fermée", line)
                    if buf:
                        parts.append("".join(buf))
                        buf = []
                    parts.append((src[i + 2:j - 1], line))
                    i = j
                    continue
                if ch == "\n":
                    line += 1
                buf.append(ch)
                i += 1
            if buf:
                parts.append("".join(buf))
            toks.append(("str", parts, start_line))
            continue
        two = src[i:i + 2]
        if two in TWO_OPS:
            toks.append(("op", two, line))
            i += 2
            continue
        if c in ONE_OPS:
            toks.append(("op", c, line))
            i += 1
            continue
        raise CalyxError("Caractère inattendu '%s'" % c, line)
    toks.append(("eof", None, line))
    return toks


# ======================================================================
#  ANALYSE SYNTAXIQUE  (noeuds = tuples : (type, ligne, ...))
# ======================================================================

class Parser:
    def __init__(self, toks):
        self.t = toks
        self.p = 0

    # -- outils
    def peek(self, k=0):
        i = min(self.p + k, len(self.t) - 1)
        return self.t[i]

    def is_op(self, v):
        t = self.peek()
        return t[0] == "op" and t[1] == v

    def is_kw(self, v):
        t = self.peek()
        return t[0] == "kw" and t[1] == v

    def match_op(self, v):
        if self.is_op(v):
            self.p += 1
            return True
        return False

    def match_kw(self, v):
        if self.is_kw(v):
            self.p += 1
            return True
        return False

    def describe(self, t):
        if t[0] == "eof":
            return "la fin du fichier"
        if t[0] == "str":
            return "un texte"
        return "'%s'" % (t[1],)

    def expect_op(self, v, ctx=""):
        t = self.peek()
        if t[0] == "op" and t[1] == v:
            self.p += 1
            return t
        raise CalyxError("'%s' attendu%s, mais j'ai trouvé %s" % (v, ctx, self.describe(t)), t[2])

    def expect_id(self, ctx="un nom"):
        t = self.peek()
        if t[0] == "id":
            self.p += 1
            return t[1]
        raise CalyxError("%s attendu, mais j'ai trouvé %s" % (ctx, self.describe(t)), t[2])

    def semi(self):
        if self.match_op(";"):
            return
        t = self.peek()
        if (t[0] == "op" and t[1] == "}") or t[0] == "eof":
            return
        raise CalyxError("';' attendu à la fin de l'instruction (trouvé %s)" % self.describe(t), self.t[self.p - 1][2] if self.p else t[2])

    # -- programme
    def program(self):
        out = []
        while self.peek()[0] != "eof":
            out.append(self.statement())
        return out

    def expr_only(self):
        e = self.expr()
        if self.peek()[0] != "eof":
            raise CalyxError("Expression invalide dans ${...}", self.peek()[2])
        return e

    def block(self):
        t = self.expect_op("{", " pour ouvrir le bloc")
        stmts = []
        while not self.is_op("}"):
            if self.peek()[0] == "eof":
                raise CalyxError("Il manque une '}' pour fermer le bloc ouvert ligne %d" % t[2], self.peek()[2])
            stmts.append(self.statement())
        self.p += 1
        return ("block", t[2], stmts)

    # -- instructions
    def statement(self):
        ty, v, ln = self.peek()
        if ty == "kw":
            if v == "use":
                return self.use_stmt()
            if v in ("let", "const"):
                return self.let_stmt()
            if v == "fn" and self.peek(1)[0] == "id":
                return self.fn_decl()
            if v == "class":
                return self.class_decl()
            if v == "if":
                return self.if_stmt()
            if v == "while":
                self.p += 1
                cond = self.expr()
                return ("while", ln, cond, self.block())
            if v == "for":
                self.p += 1
                var = self.expect_id("le nom de la variable de boucle")
                if not self.match_kw("in"):
                    raise CalyxError("'in' attendu dans 'for %s in ...'" % var, self.peek()[2])
                it = self.expr()
                return ("for", ln, var, it, self.block())
            if v == "return":
                self.p += 1
                val = None
                if not (self.is_op(";") or self.is_op("}") or self.peek()[0] == "eof"):
                    val = self.expr()
                self.semi()
                return ("return", ln, val)
            if v == "break":
                self.p += 1
                self.semi()
                return ("break", ln)
            if v == "continue":
                self.p += 1
                self.semi()
                return ("continue", ln)
            if v == "try":
                self.p += 1
                body = self.block()
                if not self.match_kw("catch"):
                    raise CalyxError("'catch' attendu après le bloc 'try'", self.peek()[2])
                name = None
                if self.peek()[0] == "id":
                    name = self.expect_id()
                return ("try", ln, body, name, self.block())
            if v == "throw":
                self.p += 1
                val = self.expr()
                self.semi()
                return ("throw", ln, val)
        if ty == "op" and v == "{":
            return self.block()
        e = self.expr()
        self.semi()
        return ("expr", ln, e)

    def use_stmt(self):
        ln = self.peek()[2]
        self.p += 1
        t = self.peek()
        if t[0] == "path":
            self.p += 1
            path = t[1]
        elif t[0] == "str":
            self.p += 1
            if any(not isinstance(x, str) for x in t[1]):
                raise CalyxError("Le chemin d'un 'use' ne peut pas contenir ${...}", t[2])
            path = "".join(t[1])
        elif t[0] == "id":
            segs = [self.expect_id()]
            while self.match_op("/"):
                segs.append(self.expect_id("un nom de module"))
            path = "/".join(segs)
        else:
            raise CalyxError("Nom de module attendu après 'use' (ex: use test;  ou  use #int/sys;)", t[2])
        alias = None
        if self.match_kw("as"):
            alias = self.expect_id("un nom après 'as'")
        self.semi()
        return ("use", ln, path, alias)

    def let_stmt(self):
        ln = self.peek()[2]
        const = self.peek()[1] == "const"
        self.p += 1
        name = self.expect_id("un nom de variable")
        val = None
        if self.match_op("="):
            val = self.expr()
        elif const:
            raise CalyxError("Une constante doit recevoir une valeur : const %s = ...;" % name, ln)
        self.semi()
        return ("let", ln, name, val, const)

    def params(self):
        self.expect_op("(", " après le nom de la fonction")
        out = []
        while not self.is_op(")"):
            name = self.expect_id("un nom de paramètre")
            default = None
            if self.match_op("="):
                default = self.expr()
            out.append((name, default))
            if not self.match_op(","):
                break
        self.expect_op(")", " pour fermer la liste des paramètres")
        return out

    def fn_decl(self):
        ln = self.peek()[2]
        self.p += 1
        name = self.expect_id()
        params = self.params()
        body = self.block()
        return ("fndecl", ln, name, params, body[2])

    def class_decl(self):
        ln = self.peek()[2]
        self.p += 1
        name = self.expect_id("un nom de classe")
        parent = None
        if self.match_kw("extends"):
            parent = self.expect_id("le nom de la classe parente")
        self.expect_op("{", " pour ouvrir la classe")
        methods = []
        while not self.is_op("}"):
            if not self.is_kw("fn"):
                raise CalyxError("Dans une classe, seules les méthodes 'fn nom() { }' sont permises", self.peek()[2])
            d = self.fn_decl()
            methods.append((d[2], d[3], d[4]))
        self.p += 1
        return ("class", ln, name, parent, methods)

    def if_stmt(self):
        ln = self.peek()[2]
        self.p += 1
        cond = self.expr()
        then = self.block()
        els = None
        if self.match_kw("else"):
            els = self.if_stmt() if self.is_kw("if") else self.block()
        return ("if", ln, cond, then, els)

    # -- expressions
    def expr(self):
        return self.assignment()

    def assignment(self):
        left = self.or_expr()
        t = self.peek()
        if t[0] == "op" and t[1] in ("=", "+=", "-=", "*=", "/=", "%="):
            if left[0] not in ("var", "index", "attr"):
                raise CalyxError("On ne peut pas assigner à cette expression", t[2])
            self.p += 1
            right = self.assignment()
            if t[1] != "=":
                right = ("bin", t[2], t[1][0], left, right)
            return ("assign", t[2], left, right)
        return left

    def or_expr(self):
        left = self.and_expr()
        while self.is_kw("or") or self.is_op("||"):
            ln = self.peek()[2]
            self.p += 1
            left = ("logic", ln, "or", left, self.and_expr())
        return left

    def and_expr(self):
        left = self.not_expr()
        while self.is_kw("and") or self.is_op("&&"):
            ln = self.peek()[2]
            self.p += 1
            left = ("logic", ln, "and", left, self.not_expr())
        return left

    def not_expr(self):
        if self.is_kw("not") or self.is_op("!"):
            ln = self.peek()[2]
            self.p += 1
            return ("not", ln, self.not_expr())
        return self.equality()

    def equality(self):
        left = self.comparison()
        while self.is_op("==") or self.is_op("!="):
            t = self.peek()
            self.p += 1
            left = ("bin", t[2], t[1], left, self.comparison())
        return left

    def comparison(self):
        left = self.term()
        while True:
            t = self.peek()
            if (t[0] == "op" and t[1] in ("<", ">", "<=", ">=")) or (t[0] == "kw" and t[1] == "in"):
                self.p += 1
                left = ("bin", t[2], t[1], left, self.term())
            else:
                return left

    def term(self):
        left = self.factor()
        while self.is_op("+") or self.is_op("-"):
            t = self.peek()
            self.p += 1
            left = ("bin", t[2], t[1], left, self.factor())
        return left

    def factor(self):
        left = self.unary()
        while self.is_op("*") or self.is_op("/") or self.is_op("%"):
            t = self.peek()
            self.p += 1
            left = ("bin", t[2], t[1], left, self.unary())
        return left

    def unary(self):
        if self.is_op("-"):
            ln = self.peek()[2]
            self.p += 1
            return ("neg", ln, self.unary())
        return self.power()

    def power(self):
        base = self.postfix()
        if self.is_op("**"):
            ln = self.peek()[2]
            self.p += 1
            return ("bin", ln, "**", base, self.unary())
        return base

    def postfix(self):
        e = self.primary()
        while True:
            t = self.peek()
            if t[0] == "op" and t[1] == "(":
                self.p += 1
                args = []
                while not self.is_op(")"):
                    args.append(self.expr())
                    if not self.match_op(","):
                        break
                self.expect_op(")", " pour fermer l'appel")
                e = ("call", t[2], e, args)
            elif t[0] == "op" and t[1] == "[":
                self.p += 1
                idx = self.expr()
                self.expect_op("]")
                e = ("index", t[2], e, idx)
            elif t[0] == "op" and t[1] == ".":
                self.p += 1
                n = self.peek()
                if n[0] not in ("id", "kw"):
                    raise CalyxError("Nom attendu après '.'", n[2])
                self.p += 1
                e = ("attr", t[2], e, n[1])
            else:
                return e

    def primary(self):
        ty, v, ln = self.peek()
        if ty == "num":
            self.p += 1
            return ("lit", ln, v)
        if ty == "str":
            self.p += 1
            if all(isinstance(x, str) for x in v):
                return ("lit", ln, "".join(v))
            parts = []
            for x in v:
                if isinstance(x, str):
                    parts.append(x)
                else:
                    parts.append(Parser(tokenize(x[0], x[1])).expr_only())
            return ("interp", ln, parts)
        if ty == "kw":
            if v in ("true", "false", "null"):
                self.p += 1
                return ("lit", ln, {"true": True, "false": False, "null": None}[v])
            if v == "fn":
                self.p += 1
                params = self.params()
                body = self.block()
                return ("func", ln, None, params, body[2])
        if ty == "id":
            self.p += 1
            return ("var", ln, v)
        if ty == "op":
            if v == "(":
                self.p += 1
                e = self.expr()
                self.expect_op(")", " pour fermer la parenthèse")
                return e
            if v == "[":
                self.p += 1
                items = []
                while not self.is_op("]"):
                    items.append(self.expr())
                    if not self.match_op(","):
                        break
                self.expect_op("]", " pour fermer la liste")
                return ("list", ln, items)
            if v == "{":
                self.p += 1
                pairs = []
                while not self.is_op("}"):
                    k = self.peek()
                    if k[0] in ("id", "kw", "num"):
                        key = k[1]
                    elif k[0] == "str" and all(isinstance(x, str) for x in k[1]):
                        key = "".join(k[1])
                    else:
                        raise CalyxError("Clé de map invalide (utilise un nom ou un texte)", k[2])
                    self.p += 1
                    self.expect_op(":", " après la clé")
                    pairs.append((key, self.expr()))
                    if not self.match_op(","):
                        break
                self.expect_op("}", " pour fermer la map")
                return ("map", ln, pairs)
        raise CalyxError("Expression inattendue : %s" % self.describe((ty, v, ln)), ln)


# ======================================================================
#  VALEURS
# ======================================================================

I = None  # interpréteur courant


class Env:
    __slots__ = ("vars", "parent", "consts")

    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent
        self.consts = None

    def find(self, name):
        e = self
        while e is not None:
            if name in e.vars:
                return e
            e = e.parent
        return None

    def all_names(self):
        names, e = set(), self
        while e is not None:
            names.update(e.vars)
            e = e.parent
        return names


class Function:
    def __init__(self, name, params, body, closure, owner=None, file=None):
        self.name, self.params, self.body = name or "<anonyme>", params, body
        self.closure, self.owner, self.file = closure, owner, file


class BoundMethod:
    def __init__(self, func, inst):
        self.func, self.inst = func, inst


class CalyxClass:
    def __init__(self, name, parent):
        self.name, self.parent, self.methods = name, parent, {}

    def find(self, name):
        c = self
        while c is not None:
            if name in c.methods:
                return c.methods[name]
            c = c.parent
        return None


class Instance:
    def __init__(self, cls):
        self.cls, self.fields = cls, {}


class SuperProxy:
    def __init__(self, inst, cls):
        self.inst, self.cls = inst, cls


class Module:
    def __init__(self, name, members, path=None):
        self.name, self.members, self.path = name, members, path


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def type_name(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "map"
    if isinstance(v, (Function, BoundMethod)):
        return "function"
    if isinstance(v, CalyxClass):
        return "class"
    if isinstance(v, Instance):
        return v.cls.name
    if isinstance(v, Module):
        return "module"
    if callable(v):
        return "function"
    return type(v).__name__


def to_str(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float):
        if v != v:
            return "nan"
        if v in (float("inf"), float("-inf")):
            return "inf" if v > 0 else "-inf"
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return format(v, ".12g")
    if isinstance(v, str):
        return v
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(to_repr(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join("%s: %s" % (to_str(k), to_repr(x)) for k, x in v.items()) + "}"
    if isinstance(v, Instance):
        m = v.cls.find("to_string")
        if m is not None and I is not None:
            return to_str(I.call_func(m, [], v, None))
        return "<%s>" % v.cls.name
    if isinstance(v, (Function, BoundMethod)):
        f = v.func if isinstance(v, BoundMethod) else v
        return "<fn %s>" % f.name
    if isinstance(v, CalyxClass):
        return "<class %s>" % v.name
    if isinstance(v, Module):
        return "<module %s>" % v.name
    if callable(v):
        return "<fn native>"
    return str(v)


def to_repr(v):
    if isinstance(v, str):
        return '"%s"' % v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return to_str(v)


def eq(a, b):
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def truthy(v):
    return bool(v)


# ======================================================================
#  OPÉRATEURS
# ======================================================================

def binop(op, a, b, line):
    if op == "+":
        if is_num(a) and is_num(b):
            return a + b
        if isinstance(a, str) or isinstance(b, str):
            return to_str(a) + to_str(b)
        if isinstance(a, list) and isinstance(b, list):
            return a + b
        raise CalyxError("Impossible d'additionner %s et %s" % (type_name(a), type_name(b)), line)
    if op == "==":
        return eq(a, b)
    if op == "!=":
        return not eq(a, b)
    if op == "in":
        if isinstance(b, str):
            if not isinstance(a, str):
                raise CalyxError("'in' sur un texte attend un texte à gauche", line)
            return a in b
        if isinstance(b, list):
            return any(eq(a, x) for x in b)
        if isinstance(b, dict):
            return a in b if not isinstance(a, (list, dict)) else False
        raise CalyxError("'in' attend un texte, une liste ou une map à droite", line)
    if op in ("<", ">", "<=", ">="):
        if (is_num(a) and is_num(b)) or (isinstance(a, str) and isinstance(b, str)):
            return {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
        raise CalyxError("Impossible de comparer %s et %s avec '%s'" % (type_name(a), type_name(b), op), line)
    if op == "*":
        if isinstance(a, (str, list)) and is_int(b):
            return a * b
        if isinstance(b, (str, list)) and is_int(a):
            return b * a
    if not (is_num(a) and is_num(b)):
        raise CalyxError("L'opérateur '%s' attend des nombres, pas %s et %s" % (op, type_name(a), type_name(b)), line)
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if b == 0:
            raise CalyxError("Division par zéro", line)
        if is_int(a) and is_int(b) and a % b == 0:
            return a // b
        return a / b
    if op == "%":
        if b == 0:
            raise CalyxError("Modulo par zéro", line)
        return a % b
    if op == "**":
        try:
            r = a ** b
        except (ZeroDivisionError, OverflowError):
            raise CalyxError("Puissance impossible", line)
        if isinstance(r, complex):
            raise CalyxError("Résultat complexe non supporté", line)
        return r
    raise CalyxError("Opérateur inconnu '%s'" % op, line)


def get_index(obj, idx, line):
    if isinstance(obj, (list, str)):
        if not is_int(idx):
            raise CalyxError("L'index d'une liste/texte doit être un entier", line)
        n, i = len(obj), idx
        if i < 0:
            i += n
        if not 0 <= i < n:
            raise CalyxError("Index %d hors limites (taille %d)" % (idx, n), line)
        return obj[i]
    if isinstance(obj, dict):
        if isinstance(idx, (list, dict)):
            raise CalyxError("Clé de map invalide", line)
        return obj.get(idx)
    raise CalyxError("Impossible d'utiliser [ ] sur %s" % type_name(obj), line)


def set_index(obj, idx, val, line):
    if isinstance(obj, list):
        if not is_int(idx):
            raise CalyxError("L'index d'une liste doit être un entier", line)
        n, i = len(obj), idx
        if i < 0:
            i += n
        if not 0 <= i < n:
            raise CalyxError("Index %d hors limites (taille %d). Utilise push() pour ajouter." % (idx, n), line)
        obj[i] = val
    elif isinstance(obj, dict):
        if isinstance(idx, (list, dict)):
            raise CalyxError("Clé de map invalide", line)
        obj[idx] = val
    else:
        raise CalyxError("Impossible d'assigner avec [ ] sur %s" % type_name(obj), line)


# ======================================================================
#  MÉTHODES DES TYPES DE BASE  (texte.upper(), liste.push(x), map.keys()...)
# ======================================================================

def call_value(f, args):
    return I.call(f, list(args), None)


def _sort_list(lst, key=None):
    if key is None:
        try:
            lst.sort()
        except TypeError:
            raise CalyxError("sort() : éléments non comparables")
    else:
        lst.sort(key=lambda x: call_value(key, [x]))
    return lst


def _need_int(v, what):
    if not is_int(v):
        raise CalyxError("%s doit être un entier" % what)
    return v


STR_METHODS = {
    "len": len,
    "upper": lambda s: s.upper(),
    "lower": lambda s: s.lower(),
    "capitalize": lambda s: s.capitalize(),
    "trim": lambda s: s.strip(),
    "split": lambda s, sep=None: s.split(sep) if sep != "" else list(s),
    "replace": lambda s, a, b: s.replace(to_str(a), to_str(b)),
    "contains": lambda s, x: to_str(x) in s,
    "starts_with": lambda s, x: s.startswith(x),
    "ends_with": lambda s, x: s.endswith(x),
    "find": lambda s, x: s.find(x),
    "repeat": lambda s, n: s * _need_int(n, "repeat()"),
    "reverse": lambda s: s[::-1],
    "slice": lambda s, a, b=None: s[a:b],
    "pad_left": lambda s, n, c=" ": s.rjust(n, c),
    "pad_right": lambda s, n, c=" ": s.ljust(n, c),
    "chars": lambda s: list(s),
}


def _list_pop(lst, i=-1):
    if not lst:
        raise CalyxError("pop() sur une liste vide")
    return lst.pop(i)


def _list_insert(lst, i, x):
    lst.insert(i, x)


def _list_remove_at(lst, i):
    n = len(lst)
    if not 0 <= i < n:
        raise CalyxError("remove_at() : index %s hors limites" % i)
    return lst.pop(i)


def _list_index_of(lst, x):
    for i, y in enumerate(lst):
        if eq(x, y):
            return i
    return -1


def _list_reduce(lst, f, init=None):
    acc = init
    items = list(lst)
    if init is None:
        if not items:
            return None
        acc, items = items[0], items[1:]
    for x in items:
        acc = call_value(f, [acc, x])
    return acc


def _join(lst, sep=""):
    return to_str(sep).join(to_str(x) for x in lst)


LIST_METHODS = {
    "len": len,
    "push": lambda l, *xs: l.extend(xs),
    "pop": _list_pop,
    "insert": _list_insert,
    "remove_at": _list_remove_at,
    "clear": lambda l: l.clear(),
    "join": _join,
    "reverse": lambda l: (l.reverse(), l)[1],
    "sort": _sort_list,
    "contains": lambda l, x: any(eq(x, y) for y in l),
    "index_of": _list_index_of,
    "slice": lambda l, a, b=None: l[a:b],
    "first": lambda l: l[0] if l else None,
    "last": lambda l: l[-1] if l else None,
    "map": lambda l, f: [call_value(f, [x]) for x in list(l)],
    "filter": lambda l, f: [x for x in list(l) if truthy(call_value(f, [x]))],
    "each": lambda l, f: [call_value(f, [x]) for x in list(l)] and None,
    "reduce": _list_reduce,
}

MAP_METHODS = {
    "len": len,
    "keys": lambda d: list(d.keys()),
    "values": lambda d: list(d.values()),
    "items": lambda d: [[k, v] for k, v in d.items()],
    "has": lambda d, k: k in d if not isinstance(k, (list, dict)) else False,
    "get": lambda d, k, default=None: d.get(k, default),
    "remove": lambda d, k: d.pop(k, None),
    "clear": lambda d: d.clear(),
}


# ======================================================================
#  FONCTIONS INTÉGRÉES
# ======================================================================

def b_print(*a):
    sys.stdout.write(" ".join(to_str(x) for x in a) + "\n")
    sys.stdout.flush()


def b_input(prompt=""):
    try:
        return input(to_str(prompt))
    except EOFError:
        return None


def b_int(v):
    try:
        if isinstance(v, str):
            s = v.strip()
            try:
                return int(s)
            except ValueError:
                return int(float(s))
        if is_num(v) or isinstance(v, bool):
            return int(v)
    except (ValueError, OverflowError):
        pass
    raise CalyxError("Impossible de convertir %s en entier" % to_repr(v))


def b_float(v):
    try:
        if isinstance(v, (str, int, float)):
            return float(v)
    except ValueError:
        pass
    raise CalyxError("Impossible de convertir %s en nombre" % to_repr(v))


def b_len(v):
    if isinstance(v, (str, list, dict)):
        return len(v)
    raise CalyxError("len() ne marche pas sur %s" % type_name(v))


def b_range(a, b=None, step=1):
    if b is None:
        a, b = 0, a
    if not (is_int(a) and is_int(b) and is_int(step)):
        raise CalyxError("range() attend des entiers")
    if step == 0:
        raise CalyxError("Le pas de range() ne peut pas être 0")
    return list(range(a, b, step))


def b_round(x, nd=0):
    if not is_num(x):
        raise CalyxError("round() attend un nombre")
    r = round(x, nd)
    return int(r) if nd == 0 else r


def b_minmax(fn, name):
    def f(*a):
        items = a[0] if len(a) == 1 and isinstance(a[0], list) else list(a)
        if not items:
            raise CalyxError("%s() : rien à comparer" % name)
        return fn(items)
    return f


def b_assert(cond, msg="Assertion échouée"):
    if not truthy(cond):
        raise CalyxError(to_str(msg))


BUILTINS = {
    "print": b_print,
    "input": b_input,
    "len": b_len,
    "str": to_str,
    "int": b_int,
    "float": b_float,
    "type": type_name,
    "range": b_range,
    "abs": lambda x: abs(x),
    "round": b_round,
    "min": b_minmax(min, "min"),
    "max": b_minmax(max, "max"),
    "sum": lambda l: sum(l),
    "assert": b_assert,
}


# ======================================================================
#  MODULES INTERNES  (use #int/...)
# ======================================================================

def enable_ansi():
    """Active les couleurs ANSI dans la console Windows."""
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            if k.GetConsoleMode(h, ctypes.byref(mode)):
                k.SetConsoleMode(h, mode.value | 0x0004)
        except Exception:
            pass


def make_sys():
    system = platform.system().lower()
    os_id = "macos" if system == "darwin" else system

    def now():
        d = datetime.datetime.now()
        return {"year": d.year, "month": d.month, "day": d.day, "hour": d.hour,
                "minute": d.minute, "second": d.second, "weekday": d.isoweekday()}

    def env(name, default=None):
        return os.environ.get(name, default)

    def run(cmd):
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return {"code": p.returncode, "output": p.stdout, "error": p.stderr}

    def clear():
        os.system("cls" if os.name == "nt" else "clear")

    def exit_(code=0):
        sys.stdout.flush()
        raise SystemExit(code)

    def username():
        try:
            import getpass
            return getpass.getuser()
        except Exception:
            return None

    return Module("sys", {
        "os": os_id,
        "arch": platform.machine(),
        "sep": os.sep,
        "args": list(I.script_args),
        "calyx_version": VERSION,
        "os_version": lambda: platform.platform(),
        "time": lambda: datetime.datetime.now().strftime("%H:%M:%S"),
        "date": lambda: datetime.datetime.now().strftime("%Y-%m-%d"),
        "datetime": lambda fmt="%Y-%m-%d %H:%M:%S": datetime.datetime.now().strftime(fmt),
        "now": now,
        "timestamp": time.time,
        "env": env,
        "cwd": os.getcwd,
        "home": lambda: os.path.expanduser("~"),
        "hostname": platform.node,
        "username": username,
        "cpu_count": lambda: os.cpu_count(),
        "sleep": lambda s: time.sleep(s),
        "exit": exit_,
        "clear": clear,
        "run": run,
        "modules_dir": modules_dir,
    })


def make_color():
    enable_ansi()
    if os.environ.get("CALYX_COLOR") == "1":
        on = True
    elif os.environ.get("NO_COLOR"):
        on = False
    else:
        on = sys.stdout.isatty()
    state = {"on": on}

    def paint(code):
        def f(text=""):
            t = to_str(text)
            return "\x1b[%sm%s\x1b[0m" % (code, t) if state["on"] else t
        return f

    m = {}
    names = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white", "orange"]
    for i, n in enumerate(names):
        m[n] = paint(30 + i)
        m["bg_" + n] = paint(40 + i)
        m["bright_" + n] = paint(90 + i)
    m["gray"] = paint(90)
    m["bold"], m["dim"], m["italic"], m["underline"] = paint(1), paint(2), paint(3), paint(4)
    m["rgb"] = lambda text, r, g, b: paint("38;2;%d;%d;%d" % (r, g, b))(text)
    m["bg_rgb"] = lambda text, r, g, b: paint("48;2;%d;%d;%d" % (r, g, b))(text)
    m["strip"] = lambda text: re.sub(r"\x1b\[[0-9;]*m", "", to_str(text))
    m["ok"] = lambda t: paint("32")("[OK] " + to_str(t))
    m["error"] = lambda t: paint("31")("[ERREUR] " + to_str(t))
    m["warn"] = lambda t: paint("33")("[!] " + to_str(t))
    m["info"] = lambda t: paint("36")("[i] " + to_str(t))

    def enable(flag=True):
        state["on"] = bool(flag)
    m["enable"] = enable
    return Module("color", m)


def make_math():
    def m_round(x, nd=0):
        return b_round(x, nd)
    return Module("math", {
        "pi": math.pi, "e": math.e, "inf": float("inf"),
        "sqrt": lambda x: math.sqrt(x) if x >= 0 else _raise("sqrt() d'un nombre négatif"),
        "pow": lambda a, b: a ** b,
        "floor": lambda x: math.floor(x), "ceil": lambda x: math.ceil(x),
        "round": m_round, "abs": abs,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "log": lambda x, base=math.e: math.log(x, base),
        "log10": math.log10, "exp": math.exp,
        "hypot": math.hypot, "gcd": math.gcd,
    })


def _raise(msg):
    raise CalyxError(msg)


def make_random():
    def choice(lst):
        if not lst:
            raise CalyxError("choice() sur une liste vide")
        return random.choice(lst)

    def shuffle(lst):
        random.shuffle(lst)
        return lst
    return Module("random", {
        "int": lambda a, b: random.randint(a, b),
        "float": random.random,
        "choice": choice, "shuffle": shuffle, "seed": random.seed,
    })


def make_fs():
    def read(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read()

    def write(path, text):
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(to_str(text))

    def append(path, text):
        with open(path, "a", encoding="utf-8", newline="") as f:
            f.write(to_str(text))

    def remove(path):
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

    return Module("fs", {
        "read": read, "write": write, "append": append,
        "exists": os.path.exists, "is_file": os.path.isfile, "is_dir": os.path.isdir,
        "list": lambda p=".": sorted(os.listdir(p)),
        "mkdir": lambda p: os.makedirs(p, exist_ok=True),
        "remove": remove,
        "copy": shutil.copy,
        "join": lambda *parts: os.path.join(*[to_str(x) for x in parts]),
        "basename": os.path.basename, "dirname": os.path.dirname,
        "abspath": os.path.abspath, "sep": os.sep,
    })


def make_json():
    def parse(text):
        try:
            return json.loads(text)
        except ValueError as e:
            raise CalyxError("JSON invalide : %s" % e)

    def stringify(v, indent=None):
        return json.dumps(v, indent=indent, ensure_ascii=False, default=to_str)
    return Module("json", {"parse": parse, "stringify": stringify})


def make_webserver():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs, unquote

    TYPES = {"html": "text/html; charset=utf-8", "text": "text/plain; charset=utf-8",
             "json": "application/json; charset=utf-8", "css": "text/css; charset=utf-8",
             "js": "application/javascript; charset=utf-8"}

    def error_page(code):
        name = {"linux": "Linux", "windows": "Windows", "darwin": "macOS"}.get(platform.system().lower(), platform.system())
        html = ("<html>\n<head>\n<title>Error %d</title>\n</head>\n<body>\n"
                "<h1>Error %d</h1>\n<hr>\n<p>Calyx - %s</p>\n</body>\n</html>\n") % (code, code, name)
        return code, TYPES["html"], {}, html.encode("utf-8")

    def to_response(r):
        status, ctype, headers, body = 200, TYPES["html"], {}, b""
        if isinstance(r, dict) and any(k in r for k in ("body", "json", "status", "type", "headers", "redirect")):
            status = int(r.get("status", 200))
            if "json" in r:
                body = json.dumps(r["json"], ensure_ascii=False, default=to_str).encode("utf-8")
                ctype = TYPES["json"]
            elif "body" in r:
                body = to_str(r["body"]).encode("utf-8")
            if "type" in r:
                ctype = TYPES.get(r["type"], r["type"])
            if "redirect" in r:
                status = 302
                headers["Location"] = to_str(r["redirect"])
            for k, v in (r.get("headers") or {}).items():
                headers[to_str(k)] = to_str(v)
        elif isinstance(r, (dict, list)):
            body = json.dumps(r, ensure_ascii=False, default=to_str).encode("utf-8")
            ctype = TYPES["json"]
        elif r is not None:
            body = to_str(r).encode("utf-8")
        if status >= 400 and not body:
            return error_page(status)
        return status, ctype, headers, body

    def create(port=8080):
        routes, statics = [], []
        state = {"port": port}
        lock = threading.Lock()

        def split(path):
            return [s for s in path.strip("/").split("/") if s]

        def add(method):
            def reg(path, handler):
                routes.append((method, split(path), handler))
            return reg

        def match(method, path):
            segs = [unquote(s) for s in split(path)]
            for m, pat, h in routes:
                if m != method and m != "ANY":
                    continue
                params, ok = {}, True
                if pat and pat[-1] == "*":
                    if len(segs) < len(pat) - 1:
                        continue
                    check = list(zip(pat[:-1], segs))
                    params["rest"] = "/".join(segs[len(pat) - 1:])
                else:
                    if len(pat) != len(segs):
                        continue
                    check = list(zip(pat, segs))
                for p, s in check:
                    if p.startswith(":"):
                        params[p[1:]] = s
                    elif p != s:
                        ok = False
                        break
                if ok:
                    return h, params
            return None, None

        def serve_static(path):
            for prefix, folder in statics:
                pre = "/" + prefix.strip("/")
                if path == pre or path.startswith(pre.rstrip("/") + "/") or pre == "/":
                    rel = unquote(path[len(pre):]).lstrip("/") if pre != "/" else unquote(path).lstrip("/")
                    root = os.path.abspath(folder)
                    full = os.path.abspath(os.path.join(root, rel))
                    if full != root and not full.startswith(root + os.sep):
                        return None
                    if os.path.isdir(full):
                        full = os.path.join(full, "index.html")
                    if os.path.isfile(full):
                        with open(full, "rb") as f:
                            data = f.read()
                        ct = mimetypes.guess_type(full)[0] or "application/octet-stream"
                        return 200, ct, {}, data
            return None

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def handle_any(self, method):
                u = urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
                headers = {k.lower(): v for k, v in self.headers.items()}
                parsed = None
                if body and "json" in headers.get("content-type", ""):
                    try:
                        parsed = json.loads(body)
                    except ValueError:
                        parsed = None
                query = {k: (v[0] if len(v) == 1 else v) for k, v in parse_qs(u.query).items()}
                handler, params = match(method, u.path)
                result = error_page(404)
                try:
                    if handler is not None:
                        req = {"method": method, "path": u.path, "query": query, "params": params,
                               "headers": headers, "body": body, "json": parsed,
                               "ip": self.client_address[0]}
                        with lock:
                            result = to_response(I.call(handler, [req], None))
                    else:
                        st = serve_static(u.path) if method == "GET" else None
                        if st:
                            result = st
                except CalyxError as e:
                    sys.stderr.write("Erreur serveur (ligne %s) : %s\n" % (e.line, e.msg))
                    result = error_page(500)
                except Exception as e:
                    sys.stderr.write("Erreur serveur : %s\n" % e)
                    result = error_page(500)
                status, ctype, extra, data = result
                print("[%s] %s %s -> %d" % (time.strftime("%H:%M:%S"), method, u.path, status))
                sys.stdout.flush()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                for k, v in extra.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self.handle_any("GET")

            def do_POST(self):
                self.handle_any("POST")

            def do_PUT(self):
                self.handle_any("PUT")

            def do_DELETE(self):
                self.handle_any("DELETE")

            def do_PATCH(self):
                self.handle_any("PATCH")

        def start(port=None, host="127.0.0.1"):
            p = int(port or state["port"])
            try:
                srv = ThreadingHTTPServer((host, p), Handler)
            except OSError as e:
                raise CalyxError("Impossible d'ouvrir le port %d : %s" % (p, e))
            srv.daemon_threads = True
            print("Serveur Calyx demarre : http://%s:%d   (Ctrl+C pour arreter)" % ("localhost" if host in ("127.0.0.1", "0.0.0.0") else host, p))
            sys.stdout.flush()
            try:
                srv.serve_forever()
            finally:
                srv.server_close()

        def static(prefix, folder):
            statics.append((prefix, folder))

        return Module("app", {
            "get": add("GET"), "post": add("POST"), "put": add("PUT"),
            "delete": add("DELETE"), "patch": add("PATCH"), "any": add("ANY"),
            "static": static, "start": start,
        })

    return Module("webserver", {
        "create": create,
        "json": lambda data, status=200: {"json": data, "status": status},
        "html": lambda text, status=200: {"body": text, "status": status, "type": "html"},
        "text": lambda text, status=200: {"body": text, "status": status, "type": "text"},
        "redirect": lambda url: {"redirect": url},
    })


NATIVE = {
    "sys": make_sys, "color": make_color, "webserver": make_webserver,
    "math": make_math, "random": make_random, "fs": make_fs, "json": make_json,
}


# ======================================================================
#  INTERPRÈTE
# ======================================================================

class Interpreter:
    MAX_DEPTH = 2500

    def __init__(self):
        global I
        I = self
        self.globals = Env()
        self.globals.vars.update(BUILTINS)
        self.native_cache, self.cache, self.loading = {}, {}, set()
        self.cur_dir, self.cur_file = os.getcwd(), "<stdin>"
        self.script_args = []
        self.depth = 0
        self.D = {n[2:]: getattr(self, n) for n in dir(self) if n.startswith("n_")}

    # -- exécution
    def ev(self, node, env):
        return self.D[node[0]](node, env)

    ex = ev

    def exec_list(self, stmts, env):
        D = self.D
        for s in stmts:
            D[s[0]](s, env)

    def run_source(self, src, env, filename):
        prev = self.cur_file
        self.cur_file = filename
        try:
            prog = Parser(tokenize(src)).program()
            try:
                self.exec_list(prog, env)
            except ReturnEx:
                pass
        except CalyxError as e:
            if e.file is None:
                e.file = filename
            raise
        finally:
            self.cur_file = prev

    def run_file(self, path):
        path = os.path.abspath(path)
        self.cur_dir = os.path.dirname(path)
        self.run_source(read_source(path), Env(self.globals), path)


    def run_module(self, module_name):
        segs = [x for x in module_name.replace(chr(92), "/").split("/") if x]

        if not segs:
            raise CalyxError("Nom de module vide")

        rel = os.path.join(*segs)

        candidates = [
            rel if rel.endswith(EXT) else rel + EXT,
            os.path.join(rel, "main" + EXT)
        ]

        search_dirs = [
            self.cur_dir,
            os.path.join(self.cur_dir, "modules"),
            os.getcwd(),
            modules_dir()
        ]

        found = None

        for directory in search_dirs:
            for candidate in candidates:
                path = os.path.join(directory, candidate)

                if os.path.isfile(path):
                    found = os.path.realpath(path)
                    break

            if found:
                break

        if not found:
            raise CalyxError(
                "Module '%s' introuvable." % module_name
            )

        self.run_file(found)

    # -- appels
    def call(self, f, args, line):
        if isinstance(f, Function):
            return self.call_func(f, args, None, line)
        if isinstance(f, BoundMethod):
            return self.call_func(f.func, args, f.inst, line)
        if isinstance(f, CalyxClass):
            inst = Instance(f)
            init = f.find("init")
            if init is not None:
                self.call_func(init, args, inst, line)
            elif args:
                raise CalyxError("La classe '%s' n'a pas de méthode init : elle n'accepte pas d'arguments" % f.name, line)
            return inst
        if callable(f):
            try:
                return f(*args)
            except CalyxError as e:
                if e.line is None:
                    e.line = line
                raise
            except SystemExit:
                raise
            except TypeError as e:
                raise CalyxError("Mauvais arguments pour cette fonction (%s)" % e, line)
            except Exception as e:
                raise CalyxError("%s : %s" % (type(e).__name__, e), line)
        raise CalyxError("'%s' n'est pas une fonction et ne peut pas être appelé" % to_str(f), line)

    def call_func(self, func, args, inst, line):
        params = func.params
        if len(args) > len(params):
            raise CalyxError("'%s' attend au plus %d argument(s), reçu %d" % (func.name, len(params), len(args)), line)
        env = Env(func.closure)
        if inst is not None:
            env.vars["self"] = inst
            if func.owner is not None and func.owner.parent is not None:
                env.vars["super"] = SuperProxy(inst, func.owner.parent)
        for i, (pn, dflt) in enumerate(params):
            if i < len(args):
                env.vars[pn] = args[i]
            elif dflt is not None:
                env.vars[pn] = self.ev(dflt, env)
            else:
                raise CalyxError("Argument '%s' manquant pour '%s'" % (pn, func.name), line)
        self.depth += 1
        if self.depth > self.MAX_DEPTH:
            self.depth -= 1
            raise CalyxError("Récursion trop profonde (plus de %d appels imbriqués)" % self.MAX_DEPTH, line)
        try:
            self.exec_list(func.body, env)
        except ReturnEx as r:
            return r.value
        except CalyxError as e:
            if e.file is None:
                e.file = func.file
            raise
        finally:
            self.depth -= 1
        return None

    # -- attributs
    def get_attr(self, obj, name, line):
        if isinstance(obj, Instance):
            if name in obj.fields:
                return obj.fields[name]
            m = obj.cls.find(name)
            if m is not None:
                return BoundMethod(m, obj)
            raise CalyxError("'%s' n'a pas de propriété ni de méthode '%s'" % (obj.cls.name, name), line)
        if isinstance(obj, Module):
            if name in obj.members:
                return obj.members[name]
            close = difflib.get_close_matches(name, list(obj.members), n=1)
            hint = " Tu voulais dire '%s' ?" % close[0] if close else ""
            raise CalyxError("Le module '%s' n'a pas de '%s'.%s" % (obj.name, name, hint), line)
        if isinstance(obj, SuperProxy):
            m = obj.cls.find(name)
            if m is None:
                raise CalyxError("La classe parente n'a pas de méthode '%s'" % name, line)
            return BoundMethod(m, obj.inst)
        table = None
        if isinstance(obj, dict):
            if name in obj:
                return obj[name]
            table = MAP_METHODS
            if name not in table:
                return None
        elif isinstance(obj, str):
            table = STR_METHODS
        elif isinstance(obj, list):
            table = LIST_METHODS
        if table is not None and name in table:
            return functools.partial(table[name], obj)
        if table is not None:
            raise CalyxError("Un(e) %s n'a pas de méthode '%s'" % (type_name(obj), name), line)
        raise CalyxError("Impossible de lire '.%s' sur %s" % (name, type_name(obj)), line)

    def set_attr(self, obj, name, val, line):
        if isinstance(obj, Instance):
            obj.fields[name] = val
        elif isinstance(obj, dict):
            obj[name] = val
        elif isinstance(obj, Module):
            obj.members[name] = val
        else:
            raise CalyxError("Impossible d'assigner '.%s' sur %s" % (name, type_name(obj)), line)

    # -- modules
    def load_module(self, path, line):
        if path.startswith("#"):
            if not path.startswith("#int/"):
                raise CalyxError("Préfixe inconnu dans '%s' (les modules internes s'écrivent #int/nom)" % path, line)
            key = path[5:]
            if key not in NATIVE:
                raise CalyxError("Module interne '%s' introuvable. Disponibles : %s" % (key, ", ".join(sorted(NATIVE))), line)
            if key not in self.native_cache:
                self.native_cache[key] = NATIVE[key]()
            return key, self.native_cache[key]
        segs = [s for s in path.replace("\\", "/").split("/") if s]
        if not segs:
            raise CalyxError("Nom de module vide", line)
        name = segs[-1][:-len(EXT)] if segs[-1].endswith(EXT) else segs[-1]
        rel = os.path.join(*segs)
        cands = [rel if rel.endswith(EXT) else rel + EXT, os.path.join(rel, "main" + EXT)]
        dirs = []
        for d in (self.cur_dir, os.path.join(self.cur_dir, "modules"), os.getcwd(), modules_dir()):
            if d not in dirs:
                dirs.append(d)
        found = None
        for d in dirs:
            for c in cands:
                full = os.path.join(d, c)
                if os.path.isfile(full):
                    found = os.path.realpath(full)
                    break
            if found:
                break
        if not found:
            raise CalyxError("Module '%s' introuvable. Cherché dans :\n  - %s" % (path, "\n  - ".join(dirs)), line)
        if found in self.cache:
            return name, self.cache[found]
        if found in self.loading:
            raise CalyxError("Import circulaire détecté avec '%s'" % path, line)
        self.loading.add(found)
        prev_dir = self.cur_dir
        self.cur_dir = os.path.dirname(found)
        env = Env(self.globals)
        try:
            self.run_source(read_source(found), env, found)
        finally:
            self.cur_dir = prev_dir
            self.loading.discard(found)
        mod = Module(name, {k: v for k, v in env.vars.items() if not k.startswith("_")}, found)
        self.cache[found] = mod
        return name, mod

    # -- instructions
    def n_expr(self, node, env):
        self.ev(node[2], env)

    def n_use(self, node, env):
        name, mod = self.load_module(node[2], node[1])
        env.vars[node[3] or name] = mod

    def n_let(self, node, env):
        _, ln, name, expr, const = node
        env.vars[name] = self.ev(expr, env) if expr is not None else None
        if const:
            if env.consts is None:
                env.consts = set()
            env.consts.add(name)

    def n_fndecl(self, node, env):
        env.vars[node[2]] = Function(node[2], node[3], node[4], env, None, self.cur_file)

    def n_class(self, node, env):
        _, ln, name, parent, methods = node
        p = None
        if parent:
            e = env.find(parent)
            p = e.vars[parent] if e else None
            if not isinstance(p, CalyxClass):
                raise CalyxError("La classe parente '%s' est introuvable" % parent, ln)
        cls = CalyxClass(name, p)
        for mname, params, body in methods:
            cls.methods[mname] = Function(mname, params, body, env, cls, self.cur_file)
        env.vars[name] = cls

    def n_block(self, node, env):
        self.exec_list(node[2], Env(env))

    def n_if(self, node, env):
        if truthy(self.ev(node[2], env)):
            self.ev(node[3], env)
        elif node[4] is not None:
            self.ev(node[4], env)

    def n_while(self, node, env):
        cond, body = node[2], node[3][2]
        while truthy(self.ev(cond, env)):
            try:
                self.exec_list(body, Env(env))
            except BreakEx:
                break
            except ContinueEx:
                continue

    def n_for(self, node, env):
        _, ln, var, it, body = node
        seq = self.ev(it, env)
        if isinstance(seq, dict):
            seq = list(seq.keys())
        elif isinstance(seq, (list, str)):
            seq = list(seq)
        else:
            raise CalyxError("'for' attend une liste, un texte ou une map (reçu %s). Pour compter : range(n)" % type_name(seq), ln)
        for item in seq:
            e2 = Env(env)
            e2.vars[var] = item
            try:
                self.exec_list(body[2], e2)
            except BreakEx:
                break
            except ContinueEx:
                continue

    def n_return(self, node, env):
        raise ReturnEx(self.ev(node[2], env) if node[2] is not None else None)

    def n_break(self, node, env):
        raise BreakEx()

    def n_continue(self, node, env):
        raise ContinueEx()

    def n_throw(self, node, env):
        v = self.ev(node[2], env)
        raise CalyxError(to_str(v), node[1], v)

    def n_try(self, node, env):
        _, ln, body, name, handler = node
        depth = self.depth
        try:
            self.ev(body, env)
        except CalyxError as e:
            self.depth = depth
            e2 = Env(env)
            if name:
                e2.vars[name] = e.value
            self.exec_list(handler[2], e2)

    # -- expressions
    def n_lit(self, node, env):
        return node[2]

    def n_interp(self, node, env):
        return "".join(p if isinstance(p, str) else to_str(self.ev(p, env)) for p in node[2])

    def n_var(self, node, env):
        name = node[2]
        e = env
        while e is not None:
            if name in e.vars:
                return e.vars[name]
            e = e.parent
        close = difflib.get_close_matches(name, list(env.all_names()), n=1)
        hint = " Tu voulais dire '%s' ?" % close[0] if close else " (déclare-la avec let, ou importe le module avec use)"
        raise CalyxError("Variable '%s' inconnue.%s" % (name, hint), node[1])

    def n_list(self, node, env):
        return [self.ev(x, env) for x in node[2]]

    def n_map(self, node, env):
        return {k: self.ev(v, env) for k, v in node[2]}

    def n_func(self, node, env):
        return Function(None, node[3], node[4], env, None, self.cur_file)

    def n_call(self, node, env):
        f = self.ev(node[2], env)
        args = [self.ev(a, env) for a in node[3]]
        return self.call(f, args, node[1])

    def n_index(self, node, env):
        return get_index(self.ev(node[2], env), self.ev(node[3], env), node[1])

    def n_attr(self, node, env):
        return self.get_attr(self.ev(node[2], env), node[3], node[1])

    def n_bin(self, node, env):
        return binop(node[2], self.ev(node[3], env), self.ev(node[4], env), node[1])

    def n_logic(self, node, env):
        a = self.ev(node[3], env)
        if node[2] == "or":
            return a if truthy(a) else self.ev(node[4], env)
        return self.ev(node[4], env) if truthy(a) else a

    def n_not(self, node, env):
        return not truthy(self.ev(node[2], env))

    def n_neg(self, node, env):
        v = self.ev(node[2], env)
        if not is_num(v):
            raise CalyxError("Le signe '-' attend un nombre, pas %s" % type_name(v), node[1])
        return -v

    def n_assign(self, node, env):
        _, ln, target, valnode = node
        val = self.ev(valnode, env)
        kind = target[0]
        if kind == "var":
            name = target[2]
            e = env.find(name)
            if e is None:
                close = difflib.get_close_matches(name, list(env.all_names()), n=1)
                hint = " Tu voulais dire '%s' ?" % close[0] if close else " Déclare-la d'abord avec let."
                raise CalyxError("Variable '%s' inconnue.%s" % (name, hint), ln)
            if e.consts and name in e.consts:
                raise CalyxError("'%s' est une constante (const), on ne peut pas la modifier" % name, ln)
            e.vars[name] = val
        elif kind == "index":
            set_index(self.ev(target[2], env), self.ev(target[3], env), val, ln)
        else:
            self.set_attr(self.ev(target[2], env), target[3], val, ln)
        return val


# ======================================================================
#  AFFICHAGE DES ERREURS
# ======================================================================

def report_error(e):
    use_color = sys.stderr.isatty() and not os.environ.get("NO_COLOR")
    red = (lambda s: "\x1b[31;1m%s\x1b[0m" % s) if use_color else (lambda s: s)
    gray = (lambda s: "\x1b[90m%s\x1b[0m" % s) if use_color else (lambda s: s)
    where = ""
    if e.file and e.file != "<stdin>":
        where = "%s" % e.file + (":%s" % e.line if e.line else "")
    elif e.line:
        where = "ligne %s" % e.line
    sys.stderr.write(red("Erreur") + " : " + e.msg + "\n")
    if where:
        sys.stderr.write(gray("  --> " + where) + "\n")
    if e.file and e.line and os.path.isfile(e.file):
        try:
            lines = read_source(e.file).split("\n")
            if 1 <= e.line <= len(lines):
                sys.stderr.write(gray("  %4d | " % e.line) + lines[e.line - 1].rstrip() + "\n")
        except Exception:
            pass
    sys.stderr.flush()


# ======================================================================
#  LIGNE DE COMMANDE
# ======================================================================

HELP = """Calyx %s - langage simple et modulaire

Utilisation :
  calyx script.cx [args...]    exécuter un programme
  calyx                        console interactive
  calyx install module.cx      installer un module pour tous vos projets
  calyx modules                lister les modules installés
  calyx --version              afficher la version

Dossier des modules universels :
  %s
""" % (VERSION, modules_dir())


def is_incomplete(src):
    depth, q, i, n = 0, None, 0, len(src)
    while i < n:
        c = src[i]
        if q:
            if c == "\\":
                i += 1
            elif c == q:
                q = None
        elif c in "\"'":
            q = c
        elif c == "/" and src[i + 1:i + 2] == "/":
            while i < n and src[i] != "\n":
                i += 1
        elif c in "{([":
            depth += 1
        elif c in "})]":
            depth -= 1
        i += 1
    return depth > 0 or q is not None


def history_path():
    return os.path.join(os.path.dirname(modules_dir()), "history")


def setup_readline(env):
    """Historique (flèches haut/bas), édition (gauche/droite) et complétion (Tab).
    Linux/macOS : module readline. Windows : la console gère déjà les flèches ;
    si pyreadline3 est installé, il est utilisé en plus (facultatif)."""
    try:
        import readline
    except ImportError:
        return lambda: None
    hist = history_path()
    try:
        os.makedirs(os.path.dirname(hist), exist_ok=True)
        readline.read_history_file(hist)
    except Exception:
        pass
    try:
        readline.set_history_length(1000)
        readline.set_completer_delims(" \t\n()[]{},;+-*/%=<>!")
        if "libedit" in (readline.__doc__ or ""):
            readline.parse_and_bind("bind ^I rl_complete")
        else:
            readline.parse_and_bind("tab: complete")

        def completer(text, state):
            try:
                if "." in text:
                    head, _, part = text.rpartition(".")
                    e = env.find(head)
                    obj = e.vars[head] if e else None
                    if isinstance(obj, Module):
                        names = list(obj.members)
                    elif isinstance(obj, dict):
                        names = [k for k in obj if isinstance(k, str)]
                    else:
                        names = []
                    opts = [head + "." + n for n in sorted(names) if n.startswith(part)]
                else:
                    names = set(KEYWORDS) | env.all_names()
                    opts = sorted(n for n in names if n.startswith(text))
                return opts[state] if state < len(opts) else None
            except Exception:
                return None
        readline.set_completer(completer)
    except Exception:
        pass

    def save():
        try:
            readline.write_history_file(hist)
        except Exception:
            pass
    return save


def repl(interp):
    print("Calyx %s - console interactive (tapez exit() ou Ctrl+D pour quitter)" % VERSION)
    env = Env(interp.globals)
    interp.globals.vars["exit"] = lambda code=0: (_ for _ in ()).throw(SystemExit(code))
    save_history = setup_readline(env)
    try:
        return _repl_loop(interp, env)
    finally:
        save_history()


def _repl_loop(interp, env):
    while True:
        try:
            src = input("calyx> ")
            while is_incomplete(src):
                src += "\n" + input("  ...  ")
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            continue
        if not src.strip():
            continue
        try:
            prog = Parser(tokenize(src)).program()
            for i, s in enumerate(prog):
                if i == len(prog) - 1 and s[0] == "expr":
                    v = interp.ev(s[2], env)
                    if v is not None:
                        print("=>", to_repr(v))
                else:
                    interp.ex(s, env)
        except CalyxError as e:
            report_error(e)
        except ControlFlow:
            sys.stderr.write("Erreur : return/break/continue en dehors d'une fonction ou d'une boucle\n")


def cmd_modules():
    d = modules_dir()
    print("Dossier des modules : " + d)
    if os.path.isdir(d):
        files = sorted(f for f in os.listdir(d) if f.endswith(EXT))
        if files:
            for f in files:
                print("  - use %s;" % f[:-len(EXT)])
        else:
            print("  (aucun module installé)")
    else:
        print("  (dossier absent - lancez l'installateur ou 'calyx install fichier.cx')")
    print("Modules internes : " + ", ".join("#int/" + k for k in sorted(NATIVE)))
    return 0


def cmd_install(path):
    if not path or not os.path.isfile(path):
        sys.stderr.write("Erreur : fichier module introuvable : %s\n" % path)
        return 1
    d = modules_dir()
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, os.path.basename(path))
    shutil.copy(path, dest)
    print("Module installé : %s\nUtilisable partout avec : use %s;" % (dest, os.path.basename(path)[:-len(EXT)] if path.endswith(EXT) else os.path.basename(path)))
    return 0


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if argv and argv[0] in ("-h", "--help", "help"):
        print(HELP)
        return 0
    if argv and argv[0] in ("-v", "--version", "version"):
        print("Calyx " + VERSION)
        return 0
    if argv and argv[0] == "modules":
        return cmd_modules()
    if argv and argv[0] == "install":
        return cmd_install(argv[1] if len(argv) > 1 else None)
    interp = Interpreter()

    if argv and argv[0] == "-m":
        if len(argv) < 2:
            sys.stderr.write(
                "Erreur : nom de module manquant après -m\\n"
            )
            sys.stderr.write(
                "Utilisation : calyx -m <module> [arguments...]\\n"
            )
            return 1

        interp.script_args = argv[2:]

        try:
            interp.run_module(argv[1])
        except CalyxError as e:
            sys.stdout.flush()
            report_error(e)
            return 1
        except ControlFlow:
            sys.stderr.write(
                "Erreur : break/continue en dehors d'une boucle\\n"
            )
            return 1

        return 0

    if not argv:
        return repl(interp)
    path = argv[0]
    if not os.path.isfile(path):
        if os.path.isfile(path + EXT):
            path += EXT
        else:
            sys.stderr.write("Erreur : fichier introuvable : %s\n" % path)
            return 1
    interp.script_args = argv[1:]
    try:
        interp.run_file(path)
    except CalyxError as e:
        sys.stdout.flush()
        report_error(e)
        return 1
    except ControlFlow:
        sys.stderr.write("Erreur : break/continue en dehors d'une boucle\n")
        return 1
    return 0


def _entry():
    result = [0]

    def runner():
        try:
            result[0] = main(sys.argv[1:]) or 0
        except SystemExit as e:
            c = e.code
            result[0] = c if isinstance(c, int) else (0 if c is None else 1)
        except KeyboardInterrupt:
            result[0] = 130
        finally:
            try:
                sys.stdout.flush()
            except Exception:
                pass

    sys.setrecursionlimit(200000)
    try:
        threading.stack_size(256 * 1024 * 1024)
    except (ValueError, RuntimeError):
        pass
    t = threading.Thread(target=runner, daemon=True)
    t.start()
    try:
        while t.is_alive():
            t.join(0.2)
    except KeyboardInterrupt:
        sys.stdout.write("\nInterrompu.\n")
        sys.stdout.flush()
        os._exit(130)
    sys.exit(result[0])


if __name__ == "__main__":
    _entry()
