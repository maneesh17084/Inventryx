# Data provenance and lawful use

* **All data is synthetic.** Every record is produced by `inventryx/` from a fixed seed (default `20261022`).
  No external dataset was downloaded, scraped, sampled or transformed.
* **No personal data.** There are no customers, addresses, people or contact details. Planner IDs (`PLN-nn`) and
  operator codes (`OPR-nn`) are opaque codes.
* **Names** of sites and suppliers are made up from generic word lists ("Riverside DC", "Apex Supply 0001") and do
  not refer to real organisations.
* **Public reference knowledge, used only to inform the schema and parameters (no data copied):**
  * UN dangerous-goods class numbers (2.1 flammable gas, 3 flammable liquid, 5.1 oxidizer, 8 corrosive,
    9 miscellaneous) and the general principle of segregating oxidizers from flammables and corrosives. The pairs
    in `compatibility_rule` are a simplified illustration, not a regulatory segregation table.
  * Standard warehouse practice: ABC velocity classes, golden-zone picking, return-routing heuristics, cube-per-order
    style slotting and min/max pick-face replenishment, as found in general warehousing textbooks.
* **Fields discarded / transformations:** not applicable, since no external source was used.
* **Licence:** generated data may be redistributed freely along with this repository.
