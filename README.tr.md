<div align="center">

# AI Test Review

**[English](README.md)** | **Türkçe**

**Testlerinizi AI ile yazan ve gözden geçiren, taşınabilir bir GitHub Action — her dilde.**

Küçük bir workflow dosyası ve tek bir API anahtarıyla herhangi bir repoya
ekleyin. Değişen kod için test yazar; repoda hiç test yoksa **sıfırdan komple
bir test paketi oluşturur**, ardından gerçek kaynak kod hatalarını bozuk
üretilmiş testlerden ayırt eder.

</div>

---

## Ne yapar

- **`diff` modu** — her push/PR'da, yalnızca değiştirdiğiniz fonksiyonlar için
  test üretir.
- **`full` (bootstrap) modu** — repoda **hiç test yoksa**, test dizinini
  oluşturur ve her kaynak dosya için sıfırdan bir test dosyası yazar.
- **`auto` modu** (varsayılan) — test yoksa bootstrap yapar, varsa diff.
- **Dilden bağımsız inceleme** — bir test koşusu başarısız olursa, tüm test
  çıktısı bir AI sınıflandırıcıya gider ve *bozuk test* mi *gerçek kaynak kod
  hatası* mı olduğuna karar verilir. Bozuk testler yeniden üretilip tekrar
  denenir; düzeltilemezse silinir (CI yeşil kalır). Gerçek bir hata ise
  `bug_report.md` yazılır, PR'a yorum atılır / issue açılır ve check başarısız
  olur. **Dile özgü çıktı ayrıştırma yoktur** — yeni bir dil eklemek kod değil,
  bir config preset'i meselesidir.

Yerleşik dil preset'leri: **Python** (pytest), **JavaScript/TypeScript** (Jest),
**Go**, **Rust**. Dil, reponuzdan otomatik algılanır
(`pyproject.toml` / `package.json` / `go.mod` / `Cargo.toml`).

## Kurulum (adım adım)

İki şeye ihtiyacınız var: **bir workflow dosyası** ve **repo secret'ı olarak
saklanan tek bir API anahtarı**. Entegrasyonun tamamı bu — kurulacak bir
uygulama yok, kod tabanınıza eklenecek bir şey yok.

### Adım 1 — Workflow dosyasını oluşturun

Test edilmesini istediğiniz repoda, tam olarak şu yolda bir dosya oluşturun:

```
.github/workflows/ai-test-review.yml
```

içeriği şu olacak şekilde:

```yaml
name: AI Test Review

on:
  push:
    branches: [main, master]
  pull_request:
  workflow_dispatch:        # Actions sekmesinden elle tetiklemenizi de sağlar

permissions:
  contents: read
  pull-requests: write      # bug raporunu PR'a yorum olarak atmak için gerekli
  issues: write             # push'ta issue açmak için gerekli

jobs:
  ai-test-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0    # ÖNEMLİ: git diff'lerin çözülebilmesi için tam geçmiş

      - uses: zer0dayf/ai-testgen@v1
        with:
          mode: auto
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

İnsanların en sık atladığı iki satır:

- Checkout adımındaki **`fetch-depth: 0`** — bu olmadan `diff` modunun
  karşılaştıracağı bir geçmiş olmaz ve hiçbir değişiklik bulamaz.
- **`permissions:` bloğu** — bu olmadan action yine test üretip çalıştırır, ama
  bir hata bulduğunda PR'a yorum atamaz veya issue açamaz.

> Anthropic yerine DeepSeek veya OpenAI mi kullanıyorsunuz? Son satırı
> `deepseek-api-key: ${{ secrets.DEEPSEEK_API_KEY }}` veya
> `openai-api-key: ${{ secrets.OPENAI_API_KEY }}` ile değiştirin. Yalnızca
> **bir** sağlayıcı yeterli.

### Adım 2 — Bir API anahtarı edinin

Şunlardan herhangi biri çalışır:

| Sağlayıcı | Anahtar alma adresi | Varsayılan model |
|---|---|---|
| Anthropic | https://console.anthropic.com → API Keys | `claude-sonnet-4-6` |
| DeepSeek | https://platform.deepseek.com → API Keys | `deepseek-chat` |
| OpenAI | https://platform.openai.com → API Keys | `gpt-4o` |

### Adım 3 — Anahtarı repository secret'ı olarak ekleyin

GitHub'da reponuzda:

1. **Settings → Secrets and variables → Actions** yolunu izleyin.
2. **New repository secret**'a tıklayın.
3. Adını **tam olarak** `ANTHROPIC_API_KEY` yapın (veya `DEEPSEEK_API_KEY` /
   `OPENAI_API_KEY` — workflow dosyanızda kullandığınız isimle birebir
   eşleşmeli).
4. Anahtarı değer olarak yapıştırıp kaydedin.

Secret eksik veya boşsa, action başarısız olmak yerine **yeşil check ile
atlar** — böylece fork'lar ve dış katkıcılardan gelen PR'lar güvendedir.

### Adım 4 — Push'layın ve ilk koşuyu izleyin

Workflow dosyasını commit'leyip push'layın (veya bir PR açın). Sonra **Actions**
sekmesini açıp "AI Test Review" koşusuna tıklayın. İlk koşuda:

- Reponuzda **henüz hiç test yoksa**, `auto` **full/bootstrap** modunu seçer:
  test dizinini oluşturur (ör. Python için `tests/`), her kaynak dosya için bir
  test dosyası yazar, her birini çalıştırır ve geçenleri tutar.
- Reponuzda **zaten test varsa**, `auto` **diff** modunu seçer: yalnızca o
  push/PR'da değişen kod için, geçici bir dizine (ör. `tests/generated/`) test
  üretir.

### Adım 5 — Sonuçları nerede bulacaksınız

- **Üretilen test dosyaları**, `ai-generated-tests` adlı bir workflow artifact'ı
  olarak yüklenir (koşu sayfası → *Artifacts*, 14 gün saklanır). Action
  reponuza **hiçbir şey commit'lemez** — artifact'ı indirin, testleri gözden
  geçirin ve tutmak istediklerinizi kendiniz commit'leyin.
- **Gerçek bir kaynak kod hatası bulunursa:** job başarısız olur ❌, bir
  `bug_report.md` üretilir ve — PR'da ise — **PR yorumu** olarak gönderilir;
  push'ta ise bir **GitHub issue** açılır (etiketler: `bug`, `ai-detected`).
- **Üretilen test sadece bozuksa:** otomatik düzeltilip 2 defaya kadar yeniden
  denenir, sonra silinir. CI'niz yeşil kalır — bozuk bir üretilmiş test sizi
  asla bloklamaz.

### Python dışı projeler: bir ek adım

Action'ın kendisi Python üzerinde çalışır (orkestratör), ama üretilen testleri
*çalıştırmak* için projenizin kendi araç zinciri hazır olmalıdır.
`ubuntu-latest` üzerinde Node, Go ve Rust zaten kurulu gelir, ancak projenizin
**bağımlılıklarının** yine de yüklenmesi gerekir. Ya preset'in varsayılan
kurulum komutuna güvenin (`npm ci`, `go mod download`, `cargo build --tests`,
…) ya da açıkça belirtin:

```yaml
      - uses: zer0dayf/ai-testgen@v1
        with:
          mode: auto
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          install: "npm ci && npm install --save-dev jest"
```

Alışılmış kurulum adımlarınızı (`actions/setup-node`, `actions/setup-go`, …)
action'dan *önceki* bir step olarak da ekleyebilirsiniz — aynı job içinde
çalışır.

## Yapılandırma (tamamı isteğe bağlı)

Standart proje düzenlerinde sıfır config yeterlidir. Özelleştirmek için repo
kökünüze bir `.aitestgen.toml` koyun (tam örnek:
`examples/aitestgen.toml.example`). Bir preset'ten başlayıp yalnızca farklı
olanı geçersiz kılın:

```toml
language      = "python"           # python | javascript | go | rust
source_glob   = "src/**/*.py"      # hangi dosyalar izlenecek/test edilecek
test_dir      = "tests/generated"  # diff modu buraya yazar (geçici)
bootstrap_dir = "tests"            # full modu buraya yazar (asıl test paketi)
run_cmd       = ["{py}", "-m", "pytest", "{test_path}", "-q"]
install       = "pip install -r requirements.txt pytest"
```

Her alan, action `with:` girdileri veya `AITG_*` ortam değişkenleriyle de
ayarlanabilir. Öncelik sırası (sonraki kazanır):
**preset < config dosyası < env değişkenleri < action girdileri/CLI bayrakları**.

### Action girdileri

| Girdi | Varsayılan | Notlar |
|---|---|---|
| `mode` | `auto` | `auto` \| `diff` \| `full` |
| `provider` | otomatik algılanır | `anthropic` \| `deepseek` \| `openai` |
| `model` | sağlayıcı varsayılanı | ör. `claude-sonnet-4-6` |
| `anthropic-api-key` / `deepseek-api-key` / `openai-api-key` | — | eşleşen secret'ı geçin; biri yeterli |
| `config-path` | otomatik bulunur | `.aitestgen.toml/.json` yolu |
| `language` | otomatik algılanır | preset override: `python` \| `javascript` \| `go` \| `rust` |
| `source-glob` | preset/config'den | izlenecek dosyaların git pathspec glob'u |
| `install` | preset/config'den | projenizin test bağımlılıklarını kuran shell komutu |
| `python-version` | `3.11` | yalnızca orkestratörü çalıştıran Python |

## Yerelde çalıştırın (GitHub gerekmez)

Motor, tek dosyalık sade bir CLI'dır — her CI'da veya kendi makinenizde çalışır:

```bash
pip install anthropic            # veya: openai (DeepSeek için de kullanılır)

# son commit'iniz için test üret + incele:
ANTHROPIC_API_KEY=sk-... python ai_testgen.py --mode auto --base-ref HEAD~1 --head-ref HEAD

# API anahtarı gerektirmeyen faydalı kontroller:
python ai_testgen.py --print-config          # çözümlenen config'i göster
python ai_testgen.py --mode full --dry-run   # bootstrap'in neler oluşturacağını listele
```

## Sorun giderme

| Belirti | Neden / çözüm |
|---|---|
| "No changes under the source glob — skipping" | Checkout sığ (shallow) — `fetch-depth: 0` ekleyin; veya dosyalarınız `source_glob` ile eşleşmiyor (`--print-config` ile kontrol edin). |
| "No AI API key found — skipping" | Workflow'daki secret adı oluşturduğunuzla eşleşmiyor, ya da secret *bu* repoda tanımlı değil (fork'lar secret'ları devralmaz — bu kasıtlıdır). |
| Hata bulundu ama PR yorumu / issue görünmüyor | Adım 1'deki `permissions:` bloğunu workflow'unuza ekleyin. |
| Testler "runner not found" (127) ile başarısız | Test araç zinciri kurulu değil — `install` girdisini ayarlayın veya action'dan önce bir `setup-*` adımı ekleyin. |
| Yanlış dil algılandı | `language:` değerini workflow'da veya `.aitestgen.toml`'da açıkça belirtin. |

## Yeni bir dil ekleme

Yerleşik preset'ler: `python`, `javascript`, `go`, `rust`.

`ai_testgen.py` içindeki `PRESETS`'e bir blok ekleyin, ya da alanları doğrudan
`.aitestgen.toml`'da ayarlayın. Bir preset şunlara ihtiyaç duyar: `language`,
`framework`, `source_glob`, `test_dir`, `bootstrap_dir`, `test_globs`,
`test_name`, `code_fence`, `comment_prefix`, `run_cmd`, `install` ve
`detect_files`; isteğe bağlı `extra_rules`, prompt'a dile özgü bir talimat
ekler. `run_cmd` yer tutucuları: `{py}`, `{test_path}`, `{test_dir}`, `{stem}`
(uzantısız test dosyası adı — ör. `cargo test --test {stem}`). Python dışı
hedefler için araç zinciri kurulumunu (`actions/setup-node`,
`actions/setup-go`, …) `install` girdisiyle veya action'dan önceki bir step ile
ekleyin.

**Derlenen diller (Go, Rust):** testler crate/paket'e karşı derlenir, bu yüzden
üretilen dosyalar yalnızca **public** API'yi kullanabilir. Rust'ta `cargo`,
integration testleri üst düzey `tests/` dizininden çalıştırır; bu yüzden her
iki mod da oraya yazar ve üretilen her hedef `cargo test --test {stem}` ile
koşulur. Bu dizin gerçek integration testlerle çakıştığından, zaten testleri
olan bir Rust reposunda `auto`'ya güvenmek yerine `mode: diff`'i açıkça
ayarlamak isteyebilirsiniz.

## Lisans

MIT © Efe Gungor
