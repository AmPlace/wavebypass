import {
  isLogoPackage,
  isPluginPackage,
  permissionLabel,
  pluginIdentity,
  pluginRuntimeLabel,
  pluginSchemeLabels,
  providerContractLabels,
  requestedPermissions,
} from './marketPackageUi.js'

const OPERATOR_BADGES = Object.freeze({
  移动: '移',
  电信: '电',
  联通: '联',
  广电: '广',
  教育网: '教',
})

const OPERATOR_TONES = Object.freeze({
  移动: 'market-region-sky',
  电信: 'market-region-orange',
  联通: 'market-region-rose',
  广电: 'market-region-emerald',
  教育网: 'market-region-violet',
})

const REGION_BADGES = Object.freeze({
  北京: '京', 上海: '沪', 天津: '津', 重庆: '渝',
  黑龙江: '黑', 吉林: '吉', 辽宁: '辽', 河北: '冀', 河南: '豫',
  山东: '鲁', 山西: '晋', 陕西: '陕', 甘肃: '甘', 宁夏: '宁', 青海: '青',
  新疆: '新', 内蒙古: '蒙', 西藏: '藏', 四川: '川', 贵州: '贵', 云南: '云',
  湖北: '鄂', 湖南: '湘', 江苏: '苏', 浙江: '浙', 安徽: '皖', 江西: '赣',
  福建: '闽', 广东: '粤', 广西: '桂', 海南: '琼', 香港: '港', 澳门: '澳', 台湾: '台',
})

const REGION_TONES = Object.freeze([
  'market-region-rose',
  'market-region-sky',
  'market-region-emerald',
  'market-region-orange',
])

const KIND_LABELS = Object.freeze({
  playlist: '播放列表',
  dynamic_playlist: '动态目录',
  mixed: '混合内容',
  logo_pack: 'Logo Package',
})

function clean(value) {
  return String(value || '').trim()
}

function stableTone(seed) {
  let hash = 0
  for (const char of clean(seed)) hash = (hash * 31 + char.charCodeAt(0)) >>> 0
  return REGION_TONES[hash % REGION_TONES.length]
}

function initials(value, fallback = '?') {
  const raw = clean(value)
  if (!raw) return fallback
  const latin = raw.match(/[a-z0-9]/gi)
  if (latin?.length) return latin.slice(0, 2).join('').toUpperCase()
  return Array.from(raw).slice(0, 2).join('') || fallback
}

function regionOf(pkg) {
  const region = pkg?.region || {}
  const province = clean(region.province)
  const country = clean(region.country)
  return {
    province: /^(global|world|unknown)$/i.test(province) ? '' : province,
    country: /^(global|world|unknown)$/i.test(country) ? '' : country,
  }
}

function operatorOf(pkg) {
  const values = Array.isArray(pkg?.operators) ? pkg.operators : []
  for (const value of values) {
    const raw = clean(value)
    if (/^(cmcc|china_mobile|中国移动|移动)$/i.test(raw)) return '移动'
    if (/^(ctcc|china_telecom|中国电信|电信)$/i.test(raw)) return '电信'
    if (/^(cucc|china_unicom|中国联通|联通)$/i.test(raw)) return '联通'
    if (/^(broadcast|中国广电|广电)$/i.test(raw)) return '广电'
    if (/^(cernet|教育网)$/i.test(raw)) return '教育网'
  }
  return ''
}

function explicitBadge(pkg) {
  const badge = pkg?.display?.badge
  if (!badge || typeof badge !== 'object') return null
  const text = clean(badge.text).slice(0, 3)
  if (!text) return null
  const tone = clean(badge.tone)
  return {
    text,
    toneClass: BADGE_TONE_CLASSES.has(tone) ? `market-region-${tone}` : stableTone(pkg?.id),
  }
}

const BADGE_TONE_CLASSES = new Set(['neutral', 'rose', 'sky', 'emerald', 'orange', 'violet'])

export function packageCardTitle(pkg) {
  if (!pkg) return ''
  if (!isPluginPackage(pkg)) return clean(pkg.name || pkg.id) || '未命名内容'
  const plugin = pkg.plugin || pkg.plugin_manifest || {}
  const value = plugin.display_name || pkg.name || pkg.id
  return clean(value).replace(/\s+Plugin(?:\s+Package)?$/i, '').trim() || '未命名 Plugin'
}

export function packageSourceLabel(pkg) {
  if (!pkg) return ''
  if (isPluginPackage(pkg)) return pluginIdentity(pkg) || '未声明 publisher'
  const { province, country } = regionOf(pkg)
  const operator = operatorOf(pkg)
  if (province && operator) return `${province} · ${operator}`
  if (province) return province
  if (country) return country
  if (operator) return operator
  return clean(pkg.market_source?.name || pkg.source_origin) || 'Market 源'
}

export function packageIdentity(pkg) {
  if (!pkg) return { text: '?', toneClass: 'market-region-neutral', sourceLabel: '' }
  const override = explicitBadge(pkg)
  if (override) return { ...override, sourceLabel: packageSourceLabel(pkg) }

  if (isPluginPackage(pkg)) {
    const publisher = clean(pkg.plugin?.publisher_id || pkg.plugin_manifest?.publisher_id)
    const official = /^org\.waveflow$/i.test(publisher) || /waveflow/i.test(clean(pkg.source_origin))
    return {
      text: official ? 'WF' : initials(publisher, 'P'),
      toneClass: 'market-region-violet',
      sourceLabel: packageSourceLabel(pkg),
    }
  }

  if (isLogoPackage(pkg)) {
    return { text: 'L', toneClass: 'market-region-neutral', sourceLabel: packageSourceLabel(pkg) }
  }

  const operator = operatorOf(pkg)
  if (operator) {
    return {
      text: OPERATOR_BADGES[operator] || initials(operator),
      toneClass: OPERATOR_TONES[operator] || stableTone(operator),
      sourceLabel: packageSourceLabel(pkg),
    }
  }

  const { province, country } = regionOf(pkg)
  const regionName = province || country
  if (regionName) {
    const badge = Object.entries(REGION_BADGES).find(([name]) => regionName.includes(name))?.[1]
    return {
      text: badge || initials(regionName, '全'),
      toneClass: stableTone(regionName),
      sourceLabel: packageSourceLabel(pkg),
    }
  }

  const source = clean(pkg.source_origin)
  const name = clean(pkg.name || pkg.id)
  const official = /waveflow|official|builtin/i.test(`${source} ${name}`)
  return {
    text: official ? 'WF' : initials(name),
    toneClass: official ? 'market-region-neutral' : stableTone(name),
    sourceLabel: packageSourceLabel(pkg),
  }
}

export function packageScaleLabel(pkg) {
  if (!pkg) return ''
  if (isLogoPackage(pkg)) return `${Number(pkg.logo_count || 0)} 个台标`
  if (isPluginPackage(pkg)) {
    const count = pluginSchemeLabels(pkg).length
    return count ? `${count} 个 scheme` : 'Provider 能力'
  }
  const count = Number(pkg.channel_count || 0)
  return count ? `${count} 个频道` : '可用内容'
}

export function packageSecondaryMeta(pkg) {
  if (!pkg) return ''
  if (isPluginPackage(pkg)) {
    const permissions = requestedPermissions(pkg).map(permissionLabel)
    return [pluginRuntimeLabel(pkg), permissions[0]].filter(Boolean).join(' · ')
  }
  const kind = KIND_LABELS[pkg.kind] || ''
  const origin = /^(official|builtin)$/i.test(clean(pkg.source_origin)) ? '官方 Market' : clean(pkg.market_source?.name || pkg.source_origin)
  return [origin, kind].filter(Boolean).join(' · ')
}

function pluginCapabilityLabels(pkg) {
  const labels = []
  for (const item of pkg?.plugin?.provider_contracts || []) {
    for (const feature of item?.features || []) {
      if (/resolve_stream$/i.test(String(feature))) labels.push('自动解析')
      else if (/catalog$/i.test(String(feature))) labels.push('目录')
    }
  }
  return labels
}

export function pluginCardTagItems(pkg) {
  const labels = [
    ...providerContractLabels(pkg),
    ...pluginCapabilityLabels(pkg),
  ]
  const seen = new Set()
  return labels.filter((label) => {
    const value = clean(label)
    if (!value || seen.has(value)) return false
    seen.add(value)
    return true
  }).map((label, index) => ({
    label,
    accentClass: index === 0 ? 'market-tag-blue' : '',
  }))
}
