# Créer un exécutable autonome de l'installateur Calyx

Objectif : un fichier unique (`.exe` sous Windows, binaire/app sous macOS/Linux) qui **embarque
son propre interpréteur Python** (l'utilisateur n'a pas besoin d'installer Python) et qui,
lorsqu'on double-clique dessus, **ouvre directement la fenêtre de l'installateur Calyx**.

## Pourquoi il faut compiler soi-même

Un tel exécutable est fabriqué avec **PyInstaller**, qui embarque l'interpréteur Python + les
dépendances dans le binaire. PyInstaller ne fait pas de compilation croisée : un `.exe` Windows
doit être construit **sur Windows**, un binaire macOS **sur macOS**, un binaire Linux **sur
Linux**. Il faut donc lancer le script de build correspondant sur chaque système que vous
souhaitez cibler.

## Étapes

1. Assurez-vous d'avoir Python 3.8+ installé sur la machine de build (juste pour la
   *compilation* — pas nécessaire pour l'utilisateur final).
2. Gardez tous les fichiers de ce dossier ensemble (`installer.py`, `calyx.py`, `LICENSE`,
   `assets/`, `examples/`, et le script de build).
3. Lancez le script adapté à votre système :
   - **Windows** : double-cliquez sur `build_windows.bat` (ou lancez-le depuis `cmd`).
   - **macOS / Linux** : ouvrez un terminal dans ce dossier puis `./build_unix.sh`.
4. Le script installe PyInstaller si besoin, puis génère l'exécutable dans le dossier `dist/` :
   - Windows : `dist\Calyx-Installer.exe`
   - macOS : `dist/Calyx-Installer.app` (ou `dist/Calyx-Installer`)
   - Linux : `dist/Calyx-Installer`
5. Double-cliquez sur ce fichier : la fenêtre graphique de l'installateur Calyx s'ouvre
   directement (Accueil → Progression → Résultat), exactement comme avec
   `python3 installer.py`, mais sans que Python soit requis sur la machine de l'utilisateur.

## AppImage (Linux, portable, sans installation)

Sur Linux, une alternative au binaire brut est l'**AppImage** : un seul fichier
`.AppImage` qui fonctionne sur la plupart des distributions sans rien installer,
avec une icône, un nom d'affichage propre, etc.

1. Ouvrez un terminal dans ce dossier.
2. Lancez : `./build_appimage.sh` (nécessite un accès internet la première fois,
   pour télécharger `appimagetool`, ensuite mis en cache dans `.tools/`).
3. Résultat : `Calyx-Installer-x86_64.AppImage` (le suffixe dépend de votre
   architecture, ex. `x86_64` ou `aarch64`).
4. Rendez-le exécutable si besoin : `chmod +x Calyx-Installer-x86_64.AppImage`,
   puis double-cliquez dessus (ou clic droit → "Autoriser l'exécution" selon
   votre gestionnaire de fichiers) pour lancer l'installateur.

Le script assemble un `.AppDir` (dossier standard AppImage : `usr/bin/`,
fichier `.desktop`, icône, script `AppRun`) à partir du build PyInstaller
`--onedir`, puis appelle `appimagetool` pour produire le fichier final.

## Depuis Linux, obtenir le .exe Windows sans machine Windows (Wine)

PyInstaller ne compile pas de manière croisée : il faut en principe lancer
`build_windows.bat` **sur Windows**. Si vous n'avez pas de machine Windows,
vous pouvez cross-builder via **Wine** :

1. Installez Wine une fois : `sudo apt install wine64`
2. Lancez : `./build_windows_wine.sh`
   (télécharge un Python Windows officiel, l'installe dans un préfixe Wine
   isolé `.wineprefix/`, puis y installe et exécute PyInstaller.)
3. Résultat : `dist/Calyx-Installer.exe`, un vrai exécutable Windows, à copier
   sur une machine Windows.

C'est plus fragile que de builder sur un vrai Windows (antivirus parfois plus
méfiants envers un `.exe` produit sous Wine, premier lancement de
`build_windows_wine.sh` un peu long). Si possible, préférez une vraie machine
ou VM Windows avec `build_windows.bat`.

## Remarques

- Le mode `--onefile --windowed` produit un seul fichier, sans console qui s'ouvre derrière la
  fenêtre.
- `calyx.py`, `LICENSE`, `assets/` et `examples/` sont embarqués dans l'exécutable (via
  `--add-data`) : c'est ce que `installer.py` copie ensuite vers le dossier d'installation choisi
  par l'utilisateur.
- macOS et Windows non signés : au premier lancement, il faudra parfois autoriser l'ouverture
  (clic droit → Ouvrir sur macOS ; "Informations complémentaires → Exécuter quand même" sur
  Windows Defender SmartScreen). C'est normal pour un exécutable non signé par un certificat
  payant.
- Pour changer l'icône de l'exécutable, ajoutez `--icon chemin/vers/icone.ico` (Windows,
  format `.ico`) ou `.icns` (macOS) à la commande PyInstaller dans le script de build.
- Si vous préférez un seul dossier au lieu d'un fichier unique (démarrage plus rapide), remplacez
  `--onefile` par `--onedir` dans le script.
