import contextlib
import re
import string
from functools import cached_property
from typing import Any, Dict, Optional, Tuple

from credsweeper.common.constants import MAX_LINE_LENGTH
from credsweeper.config import Config
from credsweeper.utils import Util
from credsweeper.utils.entropy_validator import EntropyValidator


class LineData:
    """Object to treat and store scanned line related data.

    Parameters:
        key: Optional[str] = None
        line: string variable, line
        line_num: int variable, number of line in file
        path: string variable, path to file
        file_type: string variable, extension of file '.txt'
        info: additional info about how the data was detected
        pattern: regex pattern, detected pattern in line
        separator: optional string variable, separators between variable and value
        separator_start: optional variable, separator position start
        value: optional string variable, detected value in line
        variable: optional string variable, detected variable in line

    """

    quotation_marks = ('"', "'", '`')
    comment_starts = ("//", "* ", "#", "/*", "<!––", "%{", "%", "...", "(*", "--", "--[[", "#=")
    bash_param_split = re.compile("\\s+(\\-|\\||\\>|\\w+?\\>|\\&)")
    line_endings = re.compile(r"\\{1,8}[nr]")
    url_param_split = re.compile(r"(%|\\u(00){0,2})(26|3f)", flags=re.IGNORECASE)
    # some symbols e.g. double quotes cannot be in URL string https://www.ietf.org/rfc/rfc1738.txt
    # \ - was added for case of url in escaped string \u0026amp; - means escaped & in HTML
    url_scheme_part_regex = re.compile(r"[0-9A-Za-z.-]{3}")
    url_chars_not_allowed_pattern = re.compile(r'[\s"<>\[\]^~`{|}]')
    url_value_pattern = re.compile(r'[^\s&;"<>\[\]^~`{|}]+[&;][^\s=;"<>\[\]^~`{|}]{3,80}=[^\s;&="<>\[\]^~`{|}]{1,80}')
    variable_strip_pattern = string.whitespace + """,'"-;"""

    INITIAL_WRONG_POSITION = -3
    EXCEPTION_POSITION = -2

    def __init__(
            self,  #
            config: Config,  #
            line: str,  #
            line_pos: int,  #
            line_num: int,  #
            path: str,  #
            file_type: str,  #
            info: str,  #
            pattern: re.Pattern,  #
            match_obj: Optional[re.Match] = None) -> None:
        self.config = config
        self.line: str = line
        self.line_pos: int = line_pos
        self.line_num: int = line_num
        self.path: str = path
        self.file_type: str = file_type
        self.info: str = info
        self.pattern: re.Pattern = pattern
        # do not store match object due it cannot be pickled with multiprocessing

        # start - end position of matched object
        self.value_start = LineData.INITIAL_WRONG_POSITION
        self.value_end = LineData.INITIAL_WRONG_POSITION
        self.key: Optional[str] = None
        self.separator: Optional[str] = None
        self.separator_start: int = LineData.INITIAL_WRONG_POSITION
        self.separator_end: int = LineData.INITIAL_WRONG_POSITION
        self.value: Optional[str] = None
        self.variable: Optional[str] = None
        self.variable_start = LineData.INITIAL_WRONG_POSITION
        self.variable_end = LineData.INITIAL_WRONG_POSITION
        self.value_leftquote: Optional[str] = None
        self.value_rightquote: Optional[str] = None
        # is set when variable & value are in URL for any source type
        self.url_part = False

        self.initialize(match_obj)

    def compare(self, other: 'LineData') -> bool:
        """Comparison method - skip whole line and checks only when variable and value are the same"""
        if self.path == other.path \
                and self.info == other.info \
                and self.line_num == other.line_num \
                and self.value_start == other.value_start \
                and self.variable == other.variable \
                and self.value == other.value:
            return True
        else:
            return False

    def initialize(self, match_obj: Optional[re.Match] = None) -> None:
        """Apply regex to the candidate line and set internal fields based on match."""
        if not isinstance(match_obj, re.Match) and isinstance(self.pattern, re.Pattern):
            match_obj = self.pattern.search(self.line, endpos=MAX_LINE_LENGTH)
        if match_obj is None:
            return

        def get_group_from_match_obj(_match_obj: re.Match, group: str) -> Any:
            with contextlib.suppress(Exception):
                return _match_obj.group(group)
            return None

        def get_span_from_match_obj(_match_obj: re.Match, group: str) -> Tuple[int, int]:
            with contextlib.suppress(Exception):
                span = _match_obj.span(group)
                return span[0], span[1]
            return LineData.EXCEPTION_POSITION, LineData.EXCEPTION_POSITION

        self.key = get_group_from_match_obj(match_obj, "keyword")
        self.separator = get_group_from_match_obj(match_obj, "separator")
        self.separator_start, self.separator_end = get_span_from_match_obj(match_obj, "separator")
        self.value = get_group_from_match_obj(match_obj, "value")
        self.value_start, self.value_end = get_span_from_match_obj(match_obj, "value")
        self.variable = get_group_from_match_obj(match_obj, "variable")
        self.variable_start, self.variable_end = get_span_from_match_obj(match_obj, "variable")
        self.value_leftquote = get_group_from_match_obj(match_obj, "value_leftquote")
        self.value_rightquote = get_group_from_match_obj(match_obj, "value_rightquote")
        self.sanitize_value()
        self.sanitize_variable()

    def sanitize_value(self):
        """Clean found value from extra artifacts. Correct positions if changed."""
        if self.variable and self.value and not self.is_well_quoted_value:
            # sanitize is actual step for keyword pattern only
            _value = self.value
            self.clean_url_parameters()
            self.clean_bash_parameters()
            if 0 <= self.value_start and 0 <= self.value_end and len(self.value) < len(_value):
                start = _value.find(self.value)
                self.value_start += start
                self.value_end = self.value_start + len(self.value)

    def check_url_part(self) -> bool:
        """Determines whether value is part of url like line"""
        line_before_value = self.line[:self.value_start]
        url_pos = -1
        find_pos = 0
        while find_pos < self.value_start:
            # find rightmost pattern
            find_pos = line_before_value.find("://", find_pos)
            if -1 == find_pos:
                break
            else:
                url_pos = find_pos
                find_pos += 3
        # whether the line has url start pattern
        self.url_part = 3 <= url_pos
        self.url_part &= bool(self.url_scheme_part_regex.match(line_before_value, pos=url_pos - 3, endpos=url_pos))
        self.url_part &= not self.url_chars_not_allowed_pattern.search(line_before_value, pos=url_pos + 3)
        self.url_part |= self.line[self.variable_start - 1] in "?&" if 0 < self.variable_start else False
        self.url_part |= bool(self.url_value_pattern.match(self.value))
        return self.url_part

    def clean_url_parameters(self) -> None:
        """Clean url address from 'query parameters'.

        If line seem to be a URL - split by & character.
        Variable should be right most value after & or ? ([-1]). And value should be left most before & ([0])
        """
        if self.check_url_part():
            # all checks have passed - line before the value may be a URL
            self.variable = self.variable.rsplit('&')[-1].rsplit('?')[-1].rsplit(';')[-1]
            self.value = self.value.split('&', maxsplit=1)[0].split(';', maxsplit=1)[0].split('#', maxsplit=1)[0]
            if not self.variable.endswith("://"):
                # skip sanitize in case of URL credential rule
                value_spl = self.url_param_split.split(self.value)
                if len(value_spl) > 1:
                    self.value = value_spl[0]

    def clean_bash_parameters(self) -> None:
        """Split variable and value by bash special characters, if line assumed to be CLI command."""
        if self.variable.startswith("-"):
            value_spl = self.bash_param_split.split(self.value)
            # If variable name starts with `-` (usual case for args in CLI)
            #  and value can be split by bash special characters
            if len(value_spl) > 1:
                self.value = value_spl[0]
        if ' ' not in self.value and ("\\n" in self.value or "\\r" in self.value):
            value_whsp = self.line_endings.split(self.value)
            if len(value_whsp) > 1:
                self.value = value_whsp[0]

    def sanitize_variable(self) -> None:
        """Remove trailing spaces, dashes and quotations around the variable. Correct position."""
        sanitized_var_len = 0
        variable = self.variable
        while self.variable and sanitized_var_len != len(self.variable):
            sanitized_var_len = len(self.variable)
            self.variable = self.variable.strip(self.variable_strip_pattern)
        if variable and len(self.variable) < len(variable) and 0 <= self.variable_start and 0 <= self.variable_end:
            start = variable.find(self.variable)
            self.variable_start += start
            self.variable_end = self.variable_start + len(self.variable)

    def is_comment(self) -> bool:
        """Check if line with credential is a comment.

        Return:
            True if line is a comment, False otherwise

        """
        cleaned_line = self.line.strip()
        for comment_start in self.comment_starts:
            if cleaned_line.startswith(comment_start):
                return True
        return False

    @cached_property
    def is_well_quoted_value(self) -> bool:
        """Well quoted value - means the quotations must be equal"""
        if self.value_leftquote and self.value_rightquote:
            if 1 == len(self.value_leftquote):
                leftquote = self.value_leftquote
            else:
                for q in self.quotation_marks:
                    if q in self.value_leftquote:
                        leftquote = q
                        break
                else:
                    leftquote = ""

            if 1 == len(self.value_rightquote):
                rightquote = self.value_rightquote
            else:
                for q in self.quotation_marks:
                    if q in self.value_rightquote:
                        rightquote = q
                        break
                else:
                    rightquote = ""

            return bool(leftquote) and bool(rightquote) and leftquote == rightquote

        return False

    @cached_property
    def is_quoted(self) -> bool:
        """Check if variable and value in a quoted string.

        Return:
            True if candidate in a quoted string, False otherwise

        """
        left_quote = None
        if 0 < self.variable_start:
            for i in self.line[:self.variable_start]:
                if i in ('"', "'", '`'):
                    left_quote = i
                    break
        right_quote = None
        if len(self.line) > self.value_end:
            for i in self.line[self.value_end:]:
                if i in ('"', "'", '`'):
                    right_quote = i
                    break
        return bool(left_quote) and bool(right_quote) and left_quote == right_quote

    def is_source_file(self) -> bool:
        """Check if file with credential is a source code file or not (data, log, plain text).

        Return:
            True if file is source file, False otherwise

        """
        if not self.path:
            return False
        if Util.get_extension(self.path) in self.config.source_extensions:
            return True
        return False

    def is_source_file_with_quotes(self) -> bool:
        """Check if file with credential require quotation for string literals.

        Return:
            True if file require quotation, False otherwise

        """
        if not self.path:
            return False
        if Util.get_extension(self.path) in self.config.source_quote_ext:
            return True
        return False

    def __str__(self):
        return f"line: '{self.line}' | line_num: {self.line_num} | path: {self.path}" \
               f" | value: '{self.value}' | entropy_validation: {EntropyValidator(self.value)}"

    def __repr__(self):
        return str(self)

    def to_json(self) -> Dict:
        """Convert line data object to dictionary.

        Return:
            Dictionary object generated from current line data

        """
        full_output = {
            "key": self.key,
            "line": self.line,
            "line_num": self.line_num,
            "path": self.path,
            "info": self.info,
            "pattern": self.pattern.pattern,
            "separator": self.separator,
            "separator_start": self.separator_start,
            "separator_end": self.separator_end,
            "value": self.value,
            "value_start": self.value_start,
            "value_end": self.value_end,
            "variable": self.variable,
            "variable_start": self.variable_start,
            "variable_end": self.variable_end,
            "value_leftquote": self.value_leftquote,
            "value_rightquote": self.value_rightquote,
            "entropy_validation": EntropyValidator(self.value).to_dict()
        }
        reported_output = {k: v for k, v in full_output.items() if k in self.config.line_data_output}
        return reported_output
