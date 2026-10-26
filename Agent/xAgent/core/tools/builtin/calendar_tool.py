"""日历工具。"""

from __future__ import annotations

from core.tools.base import Tool, ToolParameter


def is_leap_year(year: int) -> bool:
    """判断给定年份是否为闰年。"""
    year = int(year)
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


class IsLeapYearTool(Tool):
    """判断输入的年份是否为闰年。"""

    name = "isLeapYear"
    description = "判断输入的年份是否为闰年"
    parameters = (
        ToolParameter(
            name="year",
            type="integer",
            description="要判断的年份，例如 2024",
            required=True,
        ),
    )

    def invoke(self, year: int) -> str:
        """返回中文的判断结果。"""
        year = int(year)
        return f"{year} 是闰年" if is_leap_year(year) else f"{year} 不是闰年"
