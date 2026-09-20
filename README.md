# Calyx 1.0

Langage simple et modulaire. Un seul fichier (`calyx.py`), aucune dépendance (Python 3.8+), Linux / macOS / Windows.

## Installer
```
python3 installer.py        # graphical installer (Windows: double-click)
python3 installer.py --cli  # text mode
```
Pages: **Home** (banner `assets/header.png`, *Install Now* with the OS logo, *Custom Installation*, *License*) -> **Progress** bar -> **Result** (success or error).
Replace `assets/windows.png`, `linux.png`, `macos.png` and `header.png` with your own images (same file names).
The license shown is the `LICENSE` file (MIT by default: edit it as you wish).

Then: `calyx programme.cx`, `calyx` (console), `calyx modules`, `calyx install monmodule.cx`.

Expected layout: `calyx.py  installer.py  LICENSE  assets/  examples/`

## Modules
| Instruction | Effet |
|---|---|
| `use test;` | fichier `test.cx` : dossier du script, `./modules/`, puis dossier universel |
| `use libs/outils;` | sous-dossier (les `/` fonctionnent aussi sous Windows) |
| `use test as t;` | alias |
| `use #int/sys;` | module interne : `sys.os`, `sys.time()`, `sys.date()`, `sys.env()`, `sys.exit()`... |
| `use #int/color;` | `color.red("x")`, `bold`, `rgb`, `ok/error/warn/info`... |
| `use #int/webserver;` | `webserver.create()`, `app.get/post/static/start` |
| `use #int/math`, `random`, `fs`, `json` | bonus |

Dossier universel : `~/.calyx/modules` (Linux) - `%APPDATA%\Calyx\modules` (Windows) - surchargeable via `CALYX_MODULES`.
Les noms commençant par `_` dans un module ne sont pas exportés.

## Langage en bref
```
let x = 5;  const PI = 3.14;
fn add(a, b = 1) { return a + b; }
if x > 3 { ... } else if x == 3 { ... } else { ... }
while cond { ... }     for item in liste { ... }     for i in range(10) { ... }
let l = [1, 2];  let m = { nom: "Ada" };  m.age = 36;
"Bonjour ${nom}"   // interpolation (guillemets doubles) ; 'texte brut' sans interpolation
class A { fn init(n) { self.n = n; } }   class B extends A { ... super.init(n) }
try { throw "oups"; } catch e { print(e); }
// commentaire   /* bloc */
```
