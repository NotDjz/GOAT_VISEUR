# Viseur — Crosshair Overlay

## Utilisation
Lancer `Viseur.exe` — le viseur apparaît au centre de l'écran.
Clic droit sur l'icône dans le system tray pour les options.

## Raccourcis
| Raccourci | Action |
|-----------|--------|
| `Mod+S` | Ouvrir/fermer les paramètres |
| `Mod+H` | Masquer/afficher le viseur |
| `Mod+1-0` | Changer de preset (1-10) |
| `Mod+Q` | Quitter |

`Mod` est le modificateur, `Ctrl+Alt` par défaut. Il se change dans les paramètres
(`Ctrl+Alt`, `Ctrl+Shift`, `Alt+Shift` ou `Ctrl+Alt+Shift`) si l'un de ces raccourcis
entre en conflit avec un jeu, et le choix est conservé dans `config.json`.

## Fonctions

**Profils par jeu** — associe un jeu à un preset : le viseur bascule tout seul quand le jeu
passe au premier plan, et le réglage manuel revient quand on en sort. Onglet *Profils*, bouton
*Associer ce jeu au preset affiché*.

**Codes de viseur** — chaque preset s'exporte en un code court à partager :
`VSR1-5-FFFFFF-690F96-13-1-3-1`. Copier, coller, importer. Onglet *Viseur*.

**Démarrage avec Windows** — case à cocher dans l'onglet *Général*. Ajoute un raccourci dans le
dossier Démarrage, sans rien écrire dans le registre.

## Recompiler (optionnel)
Nécessite Python 3 + `py -m pip install -r requirements.txt`
1. `py generate_icon.py`
2. `build.bat`
3. L'exe est dans `dist\Viseur.exe`
