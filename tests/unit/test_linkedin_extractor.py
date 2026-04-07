from LinkedInExtractor import LinkedInExtractor


def test_validate_image_false_for_missing_file(tmp_path):
    extractor = LinkedInExtractor(str(tmp_path / 'missing.png'))
    assert extractor.validate_image() is False


def test_detect_loop_true_for_repeated_word(tmp_path):
    extractor = LinkedInExtractor(str(tmp_path / 'img.png'))
    extractor.result = '\n'.join([
        'python python python',
        'python python python',
        'python python python',
        'python python python',
        'python python python',
    ])
    assert extractor._detect_loop() is True
    assert extractor.loop_detected is True


def test_detect_loop_false_for_varied_text(tmp_path):
    extractor = LinkedInExtractor(str(tmp_path / 'img.png'))
    extractor.result = '\n'.join([
        'backend development with api',
        'cloud deployment and ci',
        'data modeling in sql',
        'communication and teamwork',
        'testing and observability',
    ])
    assert extractor._detect_loop() is False
