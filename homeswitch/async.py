from .util import DO_NOTHING, debug


def each(items, eachFn, finalCallback=DO_NOTHING):
	results = []
	shared = {'finished': 0, 'finalCalled': False}

	def _on_each_done(idx, rvs):
		args = list(rvs)
		err = args.pop(0)
		if err:
			debug("ERRO", "Caught error during each() execution:", err)
			shared['finalCalled'] = True
			return finalCallback(err, results)
		if shared['finalCalled']:
			return

		results[idx] = tuple(args)
		shared['finished'] += 1
		if shared['finished'] == len(items):
			finalCallback(None, results)

	def _run(idx):
		eachFn(items[idx], lambda *args: _on_each_done(idx, args))

	for x in range(0, len(items)):
		results.append(None)
		_run(x)

	return results
