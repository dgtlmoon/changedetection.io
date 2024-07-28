"""Jinja2 extensions."""
import arrow
from secrets import choice

from jinja2 import nodes
from jinja2.ext import Extension

class TimeExtension(Extension):
    """Jinja2 Extension for dates and times."""

    tags = {'now'}

    def __init__(self, environment):
        """Jinja2 Extension constructor."""
        super().__init__(environment)

        environment.extend(datetime_format='%Y-%m-%d')

    def _datetime(self, timezone, operator, offset, datetime_format):
        d = arrow.now(timezone)

        # parse shift params from offset and include operator
        shift_params = {}
        for param in offset.split(','):
            interval, value = param.split('=')
            shift_params[interval.strip()] = float(operator + value.strip())
        d = d.shift(**shift_params)

        if datetime_format is None:
            datetime_format = self.environment.datetime_format
        return d.strftime(datetime_format)

    def _now(self, timezone, datetime_format):
        if datetime_format is None:
            datetime_format = self.environment.datetime_format
        return arrow.now(timezone).strftime(datetime_format)

    def parse(self, parser):
        """Parse datetime template and add datetime value."""
        lineno = next(parser.stream).lineno

        node = parser.parse_expression()

        if parser.stream.skip_if('comma'):
            datetime_format = parser.parse_expression()
        else:
            datetime_format = nodes.Const(None)

        if isinstance(node, nodes.Add):
            call_method = self.call_method(
                '_datetime',
                [node.left, nodes.Const('+'), node.right, datetime_format],
                lineno=lineno,
            )
        elif isinstance(node, nodes.Sub):
            call_method = self.call_method(
                '_datetime',
                [node.left, nodes.Const('-'), node.right, datetime_format],
                lineno=lineno,
            )
        else:
            call_method = self.call_method(
                '_now',
                [node, datetime_format],
                lineno=lineno,
            )
        return nodes.Output([call_method], lineno=lineno)