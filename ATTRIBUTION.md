# FIELDHQ credits and project history

## Upstream project

FIELDHQ is derived from [Arma Reforger Server Management Panel](https://github.com/mateuszgolebiewski-code/arma-reforger-panel), created by **Mateusz Gołębiewski**, with upstream contributions credited to **YoussefKababe**.

- [Mateusz Gołębiewski / upstream repository](https://github.com/mateuszgolebiewski-code/arma-reforger-panel)
- [YoussefKababe](https://github.com/YoussefKababe)

Upstream's README declares: **“MIT — free to use, modify and distribute.”** It did not contain a separate root license file when reviewed. FIELDHQ includes the standard MIT terms in [LICENSE](LICENSE), retaining upstream authorship alongside the FIELDHQ modifications.

The original commit history is retained. The initial release is `bb305c1`; the baseline before this fork's development is `a8aa8dd`. FIELDHQ's hosting/unit features build on that origin. Rebranding is not a claim that the software was written independently from scratch.

## FIELDHQ development

This project is maintained by **aumik116** and is developed with AI assistance using OpenAI Codex. It has expanded to multi-server hosting, isolated unit workspaces, personnel records, event attendance and other workflows described in the manuals.

### Historical code-provenance snapshot

At commit `06706ba`, a repository-local Git blame analysis attributed **908 of 17,779 nonblank source lines (about 5.1%)** to the upstream baseline. It included 112 Python, JavaScript, CSS, HTML and shell files, excluding tests, generated manual files and bundled Chart.js. Whitespace changes were ignored and moved/copied code was followed with `git blame -w -M -C -C`.

This is a historical line-provenance measurement, not a percentage of functional similarity, a determination of legal authorship, or a claim that every other line represents an independent design. The figures will change as the project evolves.

## Bundled assets

Bundled third-party assets retain their own licenses:

- **Chart.js** — [MIT license](static/chart.LICENSE.txt).
- **Barlow** — [SIL Open Font License](static/fonts/barlow-OFL.txt).
- **Barlow Condensed** — [SIL Open Font License](static/fonts/barlowcondensed-OFL.txt).

The root MIT license does not replace these bundled license notices.

## Repository identity

The product name is **FIELDHQ**, with the new repository intended at
[`aumik116/fieldhq`](https://github.com/aumik116/fieldhq). It continues the history
from [`aumik116/arma-reforger-panel-aumik-edition`](https://github.com/aumik116/arma-reforger-panel-aumik-edition).
The move does not remove upstream authorship or license obligations.

Publish the preserved history to the empty new repository before switching
production. The old repository should remain available with a notice pointing
to FIELDHQ. See the [production migration guide](docs/migrate-to-fieldhq.md).

Installed instance directories, service names and databases retain their existing
names. A new repository does not require reinstalling the panel or game servers.
