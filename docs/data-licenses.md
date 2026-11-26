# Data, annotation, and model terms

The root [MIT license](../LICENSE) covers the original workbench software and documentation. It does not replace the following asset-specific terms. The SQLite starter is a container for separately attributed assets, not a claim that every item has one license.

## NIST scan images

**Source:** Xiaoyu Alan Zheng (2019), *NIST Ballistics Toolmark Research Database*, National Institute of Standards and Technology, [DOI 10.18434/M32021](https://doi.org/10.18434/M32021), version 1.0.

The [official catalog license field](https://catalog.data.gov/dataset/nist-ballistics-toolmark-research-database) and [publisher-deposited DOI rights metadata](https://api.datacite.org/dois/10.18434/M32021) identify NIST licensing. This release relies on [NIST's published data reuse terms](https://www.nist.gov/open/license) and [copyright/distribution notice](https://www.nist.gov/disclaimer), not merely on public download access. NIST permits distribution of covered data and modifications with appropriate acknowledgments; its general site notice excepts material marked copyrighted. Our bounded source-record review found no contrary reservation for the packaged scans. This is not a CC0 declaration or an assertion that every measurement creator was a federal employee.

Retain the dataset citation, per-scan study/measurement-creator credits, applicable notices, and the dated change notice in `training/ATTRIBUTION.md`. The repository's MIT license does not relicense these images. NIST's permissions apply to the rights NIST can grant; they are not a warranty against every third-party claim.

### NIST warranty and endorsement notices

The following warranty text is reproduced from NIST's data policy:

> The data/work is provided by NIST as a public service and is expressly provided “AS IS.” NIST MAKES NO WARRANTY OF ANY KIND, EXPRESS, IMPLIED OR STATUTORY, INCLUDING, WITHOUT LIMITATION, THE IMPLIED WARRANTY OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, NON-INFRINGEMENT AND DATA ACCURACY. NIST does not warrant or make any representations regarding the use of the data or the results thereof, including but not limited to the correctness, accuracy, reliability or usefulness of the data. NIST SHALL NOT BE LIABLE AND YOU HEREBY RELEASE NIST FROM LIABILITY FOR ANY INDIRECT, CONSEQUENTIAL, SPECIAL, OR INCIDENTAL DAMAGES (INCLUDING DAMAGES FOR LOSS OF BUSINESS PROFITS, BUSINESS INTERRUPTION, LOSS OF BUSINESS INFORMATION, AND THE LIKE), WHETHER ARISING IN TORT, CONTRACT, OR OTHERWISE, ARISING FROM OR RELATING TO THE DATA (OR THE USE OF OR INABILITY TO USE THIS DATA), EVEN IF NIST HAS BEEN ADVISED OF THE POSSIBILITY OF SUCH DAMAGES.

The database also supplies this notice:

> Certain commercial equipment, instruments, or materials are identified in this database in order to specify the experimental procedure adequately. Such identification is not intended to imply recommendation or endorsement by the National Institute of Standards and Technology (NIST), nor is it intended to imply that the materials or equipment identified are necessarily the best available for the purpose.

We retain these notices without making the unsupported assertion that all measurement creators were NIST employees. No NIST endorsement of this workbench or its predictions is claimed.

## Annotations and fitted model

**Dundee source:** Muthu Rama Krishnan Mookiah, Roberto Puch-Solis, Farhan Tanvir Santo, and Busayo Ajala (creators); Niamh Nic Daeid (supervisor). (2024). *Segmentation masks for breech and firing-pin areas for a NIST dataset of firearm cartridge case Images*. University of Dundee. [DOI 10.15132/10000262](https://doi.org/10.15132/10000262). **[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/)** ([legal code](https://creativecommons.org/licenses/by/4.0/legalcode.en)).

Dundee masks were matched to the source scan and view, resized to native dimensions, and retained or edited. The project mapped the source firing-pin region to the center-pocket target and added locally reviewed annotations, including GPT-assisted drafts. Keep this credit, license/source links, and concrete modification notices with retained or adapted masks and figures reproducing them. A changed boundary is not proof of independent authorship. Dundee's mask license does not license the underlying scan images.

The project distributes its local annotation contributions and the fitted Run #3 checkpoint under **CC BY 4.0**, to the extent it has rights to license them. Credit the Cartridge Case Masking Workbench contributors and the Dundee source above, identify changes, retain supplied notices, and link the license when redistributing. Do not imply endorsement. This explicit model permission is separate from the software MIT license.

The checkpoint contains locally fitted CPU classifiers and training-mask-derived spatial priors; carrying Dundee provenance is intentional. It is not an OpenAI model or a Dundee pretrained checkpoint. GPT helped draft annotations; local fitting and inference do not call GPT. Public output ownership and contractual restrictions are different questions: this release does not assert that human review nullifies an annotation service's terms, or that every classifier automatically qualifies for an internal-use exception. No blanket model-distribution prohibition was identified in the reviewed dataset, mask, or numerical-library terms. This is a narrow scientific segmentation baseline, not a general-purpose competing assistant model.

## Scope, safety, and dependencies

The published cohort is 48 real scans: 30 train, 6 validation, and 12 test. Validation/test remain excluded from fitting; inclusion in this repository is not approval for training. The exercise scan and its annotations are not distributed. Saved reference annotations and live model predictions are distinct. No forensic validation, independent test accuracy, or suitability for evidential decisions is claimed.

Dependencies retain their own licenses and notices. Do not remove bundled wheel/runtime notices when redistributing the container. The checkpoint uses joblib/pickle serialization: load only the trusted digest-pinned artifact, never an unknown checkpoint.
