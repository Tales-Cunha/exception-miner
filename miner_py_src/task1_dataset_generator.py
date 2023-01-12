import ast
import io
from typing import List, Dict
import astunparse
import token
import tokenize
import pandas as pd
from .miner_py_utils import statement_couter, get_function_def, count_try
from .stats import TBLDStats

from numpy.random import default_rng

rng = default_rng()

INDENT_STR = f"<{token.tok_name[token.INDENT]}> "
DEDENT_STR = f"<{token.tok_name[token.DEDENT]}> "
NEWLINE_STR = f"<{token.tok_name[token.NEWLINE]}> "


class TryDatasetGenerator():

    def __init__(self, func_defs: List[ast.FunctionDef]) -> None:
        self.func_defs = func_defs
        self.stats = TBLDStats()
        self.reset()

    def reset(self):
        self.indentation_counter = 0
        self.lines = []
        self.labels = []
        self.has_catch = False
        self.start_function_def = False
        self.try_reached = False

        self.current_line = None
        self.token_buffer = []

        self.stats.num_max_tokens = max(
            self.stats.num_max_tokens, self.stats.function_tokens_acc
        )
        self.stats.tokens_count += self.stats.function_tokens_acc
        self.stats.function_tokens_acc = 0

    def generate(self):
        generated = []

        for f in self.func_defs:
            try:
                # remove lint formatting
                function_def = get_function_def(ast.parse(astunparse.unparse(f)))

                tokenized_function_def = self.tokenize_function_def(function_def)

                if tokenized_function_def is not None:
                    self.stats.functions_count += 1
                    self.stats.increment_try_stats(count_try(function_def))
                    num_statements = statement_couter(function_def)
                    self.stats.statements_count += num_statements
                    self.stats.num_max_statement = max(
                        self.stats.num_max_statement, num_statements
                    )
                    generated.append(tokenized_function_def)
            except SyntaxError as e:
                print(f"###### SyntaxError Error!!! in ast.FunctionDef {f}.\n{str(e)}")
                continue
            except ValueError as e:
                print(f"###### ValueError Error!!! in ast.FunctionDef {f}.\n{str(e)}")
                continue

        print(self.stats)
        return pd.DataFrame(generated)

    def clear_line_buffer(self):
        if len(self.token_buffer) == 0:
            return

        if self.try_reached:
            indentation = (self.indentation_counter - 1) * INDENT_STR
            self.stats.function_tokens_acc += self.indentation_counter - 1
        else:
            indentation = self.indentation_counter * INDENT_STR
            self.stats.function_tokens_acc += self.indentation_counter

        self.stats.function_tokens_acc += len(self.token_buffer)
        self.stats.unique_tokens.update(self.token_buffer)

        tokenized_line = indentation + " ".join(self.token_buffer)
        self.token_buffer = []

        self.lines.append(tokenized_line)
        self.labels.append(1 if self.try_reached else 0)
       

    def end_of_generation(self):
        res = {
            "hasCatch": 1 if self.has_catch else 0,
            "lines": self.lines,
            "labels": self.labels,
        }

        self.reset()

        return res

    def get_try_slice(self, node: ast.FunctionDef):
        for n in ast.walk(node):
            if isinstance(n, ast.Try):
                self.has_catch = len(n.handlers) != 0
                if not self.has_catch:
                    continue
                return [n.lineno, n.handlers[0].lineno]

    def handle_indentation_and_newline(self, token_info: tokenize.TokenInfo):
        return self.handle_indentation(token_info) or self.handle_new_line(token_info)

    def handle_new_line(self, token_info: tokenize.TokenInfo):
        if token_info.type == token.NEWLINE:
            self.token_buffer.append(NEWLINE_STR)
            return True
        return False

    def handle_indentation(self, token_info: tokenize.TokenInfo):
        if token_info.type == token.INDENT:
            self.indentation_counter += 1
            return True

        if token_info.type == token.DEDENT:
            self.indentation_counter -= 1
            assert self.indentation_counter >= 0
            return True
        return False

    def tokenize_function_def(self, node: ast.FunctionDef):
        assert node is not None

        try_slice = self.get_try_slice(node)

        unparsed_code = astunparse.unparse(node)
        for token_info in tokenize.generate_tokens(io.StringIO(unparsed_code).readline):
            if token_info.line != self.current_line:
                self.clear_line_buffer()
                self.current_line = token_info.line

            if try_slice is not None:
                self.try_reached = token_info.start[0] >= try_slice[0]
                if token_info.start[0] == try_slice[0]:  # ignore try
                    self.handle_indentation(token_info)
                    continue

                if token_info.start[0] >= try_slice[1]:
                    return self.end_of_generation()

            if token_info.type in [token.COMMENT, token.NL]:
                continue

            if token_info.type == token.ENDMARKER:
                return self.end_of_generation()

            if not self.handle_indentation_and_newline(token_info):
                self.token_buffer.append(token_info.string)
