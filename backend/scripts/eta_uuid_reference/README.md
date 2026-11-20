# Receipt UUID: reference from the authority's own library

`app/modules/einvoice/providers/eta/uuid_.py` implements the receipt UUID rule. The rule is not
published as text, but the authority publishes the code as a NuGet package:
`ETA.Ereceipt.UUID` 1.0.0 (MIT, author "ETAEgypt"). This folder is how we run it, without an ETA
account and without contacting the authority.

1. `dotnet new console -n Runner`, replace `Program.cs` with the file here.
2. Put `ETA-Ereceipt.dll` (from the .nupkg, `lib/net5.0/`) and `Newtonsoft.Json.dll` next to the
   built `Runner.dll`. It runs on .NET 8 (Linux is fine).
3. `compare_with_authority_library.py N` (run from `backend/` with `PYTHONPATH=.`) builds N random
   receipts with our builder, asks the library for each UUID and reports how many are identical.
   Last run: 2000 of 2000.
4. The 52 saved answers in `tests/data/eta_uuid_authority_vectors.json` let CI check the rule
   without .NET. Regenerate them only if the authority publishes a new version of the package.

Not covered: that the live service accepts the receipt (needs PreProd), and signing.
