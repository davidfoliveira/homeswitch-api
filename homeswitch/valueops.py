def apply_ops(value, ops=None):
	new_value = value
	if ops is None:
		ops = []

	for op in ops:
		new_value = apply_op(new_value, op)

	return new_value

def apply_op(value, op):
	op_type = op.get('type', None)
	if op_type == 'add':
		return value + op.get('value')
	if op_type == 'subtract':
		return value - op.get('value')
	if op_type == 'multiply':
		return value * op.get('value')
	if op_type == 'divide':
		return value / op.get('value')
	if op_type == 'xmulti':
		return value * op.get('value_max_out') / op.get('value_max_in')
	if op_type == 'absolute':
		return abs(value)
	if op_type == 'round':
		return round(value, op.get('decimals', 0))
	if op_type == 'floor':
		return floor(value)
	if op_type == 'cast':
		cast_type = op.get('cast_type', 'int')
		if cast_type == 'int':
			return int(value)
		if cast_type == 'number':
			return float(value)
		if cast_type == 'boolean':
			return bool(value)
		raise Exception('Unsupported cast type {}'.format(cast_type))
	raise Exception('Unknown operation type {}'.format(op_type))