// Prints the receipt UUID that the authority's OWN library (NuGet ETA.Ereceipt.UUID, MIT, author
// ETAEgypt) computes. One JSON document per stdin line (header.uuid empty); one UUID per line out.
// Used only to (re)generate tests/data/eta_uuid_authority_vectors.json. See README.md next to it.
using System.Reflection;

var dll = args.Length > 0 ? args[0] : "ETA-Ereceipt.dll";
var asm = Assembly.LoadFrom(dll);
const BindingFlags all = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.Instance;
var generate = asm.GetTypes().First(t => t.Name == "Manager").GetMethod("GenerateUUID", all)!;
object? self = generate.IsStatic ? null : Activator.CreateInstance(generate.DeclaringType!);
string? line;
while ((line = Console.ReadLine()) != null)
{
    if (line.Length == 0) continue;
    try { Console.WriteLine(generate.Invoke(self, new object[] { line })); }
    catch (TargetInvocationException e) { Console.WriteLine("ERR " + e.InnerException?.Message); }
}
