"""Оформление субтитра должно записываться теми же байтами, что пишет CapCut.

Оформление лежит в черновике как JSON внутри строки. Одно и то же по смыслу
содержимое можно записать по-разному: с пробелами после запятых или без, полной
записью дробного числа или сокращённой. Поэтому текст подставляется в строку
точечно, а не пересобирается целиком.
"""
from __future__ import annotations

import json

from capcut_uniq.subtitles import rewrite_content

# Ровно в таком виде оформление лежит в настоящем шаблоне.
ORIGIN = (
    '{"styles":[{"fill":{"content":{"solid":{"color":[1,1,1]},"render_type":"solid"}},'
    '"range":[0,38],"strokes":[{"width":0.059999998658895493,"mode":0,"content":'
    '{"solid":{"color":[0,0,0]},"render_type":"solid"}}],"size":12,"font":'
    '{"path":"/data/user/0/com.lemon.lvoverseas/files/resources/effect/artists/'
    '7603634169704353040/e46fca5a9bc82648fea1de961c2a3a91/font.ttf",'
    '"id":"7603634169704353040"}}],"text":"Суперсел тайно раздают Бравл Пасс плюс"}'
)


def test_same_text_gives_back_the_very_same_bytes():
    assert rewrite_content(ORIGIN, "Суперсел тайно раздают Бравл Пасс плюс") == ORIGIN


def test_no_spaces_are_introduced():
    result = rewrite_content(ORIGIN, "Короткая строка")
    assert '": ' not in result
    assert ', ' not in result


def test_long_fraction_survives():
    """Python сокращает такую запись, а CapCut пишет её полностью."""
    result = rewrite_content(ORIGIN, "Другой текст")
    assert '"width":0.059999998658895493' in result


def test_range_follows_the_new_length():
    text = "Разработчики Бравл Старс тайно раздают"
    body = json.loads(rewrite_content(ORIGIN, text))
    assert body["text"] == text
    assert body["styles"][0]["range"] == [0, len(text)]


def test_font_and_colours_are_untouched():
    before = json.loads(ORIGIN)["styles"][0]
    after = json.loads(rewrite_content(ORIGIN, "Ещё текст"))["styles"][0]
    assert after["font"] == before["font"]
    assert after["fill"] == before["fill"]
    assert after["strokes"] == before["strokes"]
    assert after["size"] == before["size"]


def test_quotes_and_backslashes_are_escaped():
    text = 'он сказал "привет" и \\ ушёл'
    body = json.loads(rewrite_content(ORIGIN, text))
    assert body["text"] == text
    assert body["styles"][0]["range"] == [0, len(text)]


def test_several_styles_all_get_the_new_length():
    origin = (
        '{"styles":[{"range":[0,5],"size":12},{"range":[0,5],"size":9}],"text":"Слово"}'
    )
    body = json.loads(rewrite_content(origin, "Длинное слово"))
    assert [s["range"] for s in body["styles"]] == [[0, 13], [0, 13]]


def test_partial_range_is_left_alone():
    """Диапазон, покрывающий часть строки, к длине текста не привязан."""
    origin = '{"styles":[{"range":[0,5]},{"range":[2,4]}],"text":"Слово"}'
    body = json.loads(rewrite_content(origin, "Слова"))
    assert body["styles"][0]["range"] == [0, 5]
    assert body["styles"][1]["range"] == [2, 4]


def test_falls_back_when_there_is_nothing_to_patch():
    body = json.loads(rewrite_content("{}", "Текст"))
    assert body["text"] == "Текст"


def test_word_text_key_inside_styles_is_not_confused():
    """Ключ text встречается и внутри оформления — правим только внешний."""
    origin = '{"styles":[{"range":[0,5],"shape":{"text":"Слово"}}],"text":"Слово"}'
    result = rewrite_content(origin, "Иначе")
    body = json.loads(result)
    assert body["text"] == "Иначе"
    assert body["styles"][0]["shape"]["text"] == "Слово"
