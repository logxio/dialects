# Privacy

This plugin makes one outbound HTTP GET request, to the URL you pass it, using
the User-Agent configured on the provider.

It sends nothing to any other host. It writes nothing to disk. It keeps no
state between invocations. The response body is read up to `max_bytes`, counted,
and discarded; only the title, the word count, and the response metadata listed
in the tool's output schema are returned.
