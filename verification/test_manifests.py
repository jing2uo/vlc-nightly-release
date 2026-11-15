"""Required manifest fields and invalid values must fail lightweight CI."""
import copy
import json
import unittest

from validate_manifests import FIELDS, PATCH_FIELDS, ROOT, validate


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifests = {name: json.loads((ROOT / name).read_text()) for name in FIELDS}

    def test_checked_in_manifests(self):
        for name, data in self.manifests.items():
            with self.subTest(name=name):
                validate(name, data)

    def test_missing_or_wrongly_typed_required_fields(self):
        for name, fields in FIELDS.items():
            for key in fields:
                for replacement in ('missing', None):
                    with self.subTest(name=name, key=key, replacement=replacement):
                        data = copy.deepcopy(self.manifests[name])
                        if replacement == 'missing':
                            del data[key]
                        else:
                            data[key] = replacement
                        with self.assertRaises(ValueError):
                            validate(name, data)

    def test_patch_fields_are_required(self):
        for key in PATCH_FIELDS:
            data = copy.deepcopy(self.manifests['patches/manifest.json'])
            del data['patches'][0][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate('patches/manifest.json', data)

    def test_invalid_manifest_values(self):
        cases = [('verification/fixtures.json', 'sha256', 'bad'),
                 ('verification/fixtures.json', 'size', 0),
                 ('verification/fixtures.json', 'url', 'http://example.invalid/media'),
                 ('verification/runtime-path-policy.json', 'schema', 2),
                 ('verification/runtime-path-policy.json', 'sources', {'../escape': 'a' * 64}),
                 ('verification/x11-waiver.json', 'architecture', 'invalid'),
                 ('verification/x11-waiver.json', 'expires_at', '2020-01-01T00:00:00Z')]
        for name, key, value in cases:
            with self.subTest(name=name, key=key):
                data = copy.deepcopy(self.manifests[name])
                data[key] = value
                with self.assertRaises(ValueError):
                    validate(name, data)


if __name__ == '__main__':
    unittest.main()
