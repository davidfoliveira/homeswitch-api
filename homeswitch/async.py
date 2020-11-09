from .util import DO_NOTHING


def each(items, eachFn, finalCallback=DO_NOTHING):
	results = []
	counters = {'finished': 0}

	def _on_each_done(idx, rvs):
		results[idx] = rvs
		counters['finished'] += 1
		if counters['finished'] == len(items):
			finalCallback(results)

	def _run(idx):
		eachFn(items[idx], lambda *args: _on_each_done(idx, args))

	for x in range(0, len(items)):
		results.append(None)
		_run(x)

	return results
