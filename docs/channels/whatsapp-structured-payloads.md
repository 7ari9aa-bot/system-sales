# WhatsApp: the structured half of a message

The report's WhatsApp gap (e): the canonical message model flattened structured payloads into a
summary string. A shared location became `📍 المخزن ١٢ شارع النيل` with no coordinates, a shared
contact became one concatenated name-and-number line, and a tapped list option lost its `id` — the
one thing a bot routes on.

`gateway/whatsapp_structured.py` rebuilds the structure from the stored webhook body, and the thread
carries it as `structured` next to the one-line `body`.

| Kind | What the thread gets |
|---|---|
| location | `latitude`, `longitude`, `name`, `address` — enough to open a map |
| contact | up to 10 cards, each with `name` and up to 5 `phones` |
| buttons / list | `kind`, `id`, `title`, `description` — `id` is what a bot answers on |
| template quick reply | `kind: template_button`, `id` (the payload), `title` |

Rules that are deliberate:

* **Checked, not passed through.** Only known fields leave the server. A location without both
  coordinates is `None`, not a half-filled card that cannot open a map; a contact with no name and no
  number is dropped rather than drawn empty.
* **Rebuilt at read time** from the stored raw body, so a row written before this existed still shows
  its pin, and a shape Meta changes later falls back to the plain text instead of breaking the thread.
* **Inbound only.** An outbound row has no customer payload to show.
* **The body stays.** Every message still has its one-line text for the chat list and for search.

## Tests

`tests/test_whatsapp_structured_payloads.py` — coordinates survive, a location without them is not a
location, contact cards keep their numbers, an empty contact is dropped, the tapped option keeps its
`id`, a template payload is kept, an unknown shape yields nothing, and the reader picks the right
shape per content type.
