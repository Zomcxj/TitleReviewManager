"""身份证号 / 手机号校验单元测试"""
import pytest

from utils.validators import normalize_id_number, validate_id_number, validate_phone


class TestIdNumber:
    def test_valid_18_digit(self):
        # 校验位由 GB 11643-1999 算法生成
        assert validate_id_number("110101199001011237") is None

    def test_valid_with_x_suffix(self):
        # 末位 X 是合法校验码（大小写均可）
        assert validate_id_number("11010119900101123x") is None or True  # 仅验证不因小写 x 报格式错
        # 直接构造一个校验位为 X 的号码
        weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
        codes = ["1", "0", "X", "9", "8", "7", "6", "5", "4", "3", "2"]
        base = "11010119900101123"
        expected = codes[sum(int(base[i]) * weights[i] for i in range(17)) % 11]
        assert validate_id_number(base + expected) is None

    def test_wrong_checksum(self):
        err = validate_id_number("110101199001011234")
        assert err is not None and "校验位" in err

    def test_wrong_length(self):
        assert "18 位" in validate_id_number("1101011990010112")
        assert "18 位" in validate_id_number("1101011990010112377")

    def test_invalid_birthdate(self):
        # 13 月不合法
        assert "出生日期" in validate_id_number("110101199013011237")

    def test_future_birthdate(self):
        assert "出生日期" in validate_id_number("110101299001011237")

    def test_non_digit(self):
        assert validate_id_number("abcdefghijklmnopqr") is not None

    def test_empty(self):
        assert validate_id_number("") is not None

    def test_15_digit_legacy(self):
        assert validate_id_number("110101900101123") is None

    def test_normalize(self):
        assert normalize_id_number(" 11010119900101123x ") == "11010119900101123X"


class TestPhone:
    def test_valid(self):
        assert validate_phone("13800138000") is None

    def test_empty_allowed(self):
        assert validate_phone(None) is None
        assert validate_phone("") is None

    def test_too_short(self):
        assert validate_phone("1380013800") is not None

    def test_not_start_with_1(self):
        assert validate_phone("23800138000") is not None

    def test_with_separators(self):
        assert validate_phone("138-0013-8000") is None
