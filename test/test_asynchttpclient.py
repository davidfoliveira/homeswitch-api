from homeswitch.http.asyncclient import AsyncHTTPClient
from homeswitch import asyncorepp

def _on_get_response(err, res):
	print "GOT RESPONSE: ", res


client = AsyncHTTPClient()
client.get("http://pz.org.pt/x?a=b&c=d", callback=_on_get_response)

asyncorepp.loop()