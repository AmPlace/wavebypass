<template>
  <main
    class="market-main min-h-screen w-full px-5 pb-32 pt-[calc(env(safe-area-inset-top)+4rem)] sm:px-8 lg:px-10 lg:pb-40 lg:pt-6"
  >
    <section class="market-filter-bar">
      <div class="market-filter-scroll">
        <div class="market-package-type-switch" aria-label="Market 包类型">
          <button v-for="item in packageTypeOptions" :key="item.key" type="button" class="market-package-type-button" :class="{ 'is-active': packageType === item.key }" @click="selectPackageType(item.key)">{{ item.label }}</button>
        </div>
        <button
          v-for="quick in quickFilterTabs"
          :key="quick.key"
          type="button"
          class="market-filter-pill"
          :class="{ 'is-active': quick.active() }"
          @click="quick.select"
        >
          {{ quick.label }}
        </button>
        <button type="button" class="market-filter-sheet-trigger" @click="filterSheetOpen = true">
          <svg class="size-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M4 6h16M7 12h10M10 18h4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          </svg>
          筛选
          <span v-if="selectedChips.length" class="market-filter-count">{{ selectedChips.length }}</span>
        </button>
        <MarketFilterDropdown
          v-for="group in visibleFilterGroups"
          :key="group.key"
          :label="group.label"
          :options="group.options()"
          :selected="filterMultiSelections[group.key]"
          :multi="true"
          :dropdown-key="group.key"
          :open="activeDropdownKey === group.key"
          class="market-desktop-filter"
          @change="(values) => onMultiFilterChange(group.key, values)"
          @toggle="handleDropdownToggle"
          @close="handleDropdownClose"
        />
      </div>
    </section>

    <section class="market-list-head">
      <div class="flex min-w-0 items-center gap-3">
        <span class="flex size-8 shrink-0 items-center justify-center rounded-full bg-[var(--surface)] text-[var(--text-primary)]">
          <svg class="size-4" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 8.4 12 4l8 4.4-8 4.4L4 8.4Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M4 12.2 12 16.6l8-4.4M4 16l8 4.4L20 16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </span>
        <h1 class="truncate text-lg font-semibold leading-none text-[var(--text-primary)]">{{ packageType === 'plugins' ? 'Plugin Packages' : '频道包' }}</h1>
        <span class="shrink-0 text-sm text-[var(--text-secondary)]">{{ resultCountLabel }}</span>
      </div>

      <div class="market-list-actions">
        <div class="market-inline-search" :class="{ 'is-open': searchOpen || filters.search }">
          <button
            type="button"
            class="market-action-pill market-search-trigger"
            :tabindex="searchOpen || filters.search ? -1 : 0"
            :aria-hidden="searchOpen || filters.search"
            @click="openSearch"
          >
            <svg class="size-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="1.8"/>
              <path d="M16.5 16.5 21 21" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
            </svg>
            搜索
          </button>
          <div class="market-search-field" :aria-hidden="!(searchOpen || filters.search)">
            <svg class="size-[17px] shrink-0 text-[var(--text-tertiary)]" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="1.8"/>
              <path d="M16.5 16.5 21 21" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
            </svg>
            <input
              ref="searchInputRef"
              v-model="filters.search"
              type="search"
              :placeholder="packageType === 'plugins' ? '搜索插件、publisher、scheme…' : '搜索频道包、地区、分类…'"
              class="min-w-0 flex-1 bg-transparent text-[13px] text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)]"
              :tabindex="searchOpen || filters.search ? 0 : -1"
              @keydown.esc.prevent="closeSearch"
              @blur="handleSearchBlur"
            />
            <button
              v-if="filters.search"
              type="button"
              class="flex size-6 shrink-0 items-center justify-center rounded-full text-[var(--text-tertiary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]"
              aria-label="清除搜索"
              @mousedown.prevent
              @click="filters.search = ''"
            >
              <svg class="size-3.5" viewBox="0 0 24 24" fill="none"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>
            </button>
          </div>
        </div>

        <MarketFilterDropdown
          :label="'排序'"
          :options="sortOptions"
          :selected="[filters.sort]"
          :multi="false"
          :show-count-badge="false"
          :display-as-current="true"
          :highlight-selection="false"
          dropdown-key="sort"
          menu-width-mode="compact"
          :open="activeDropdownKey === 'sort'"
          class="market-sort-dropdown"
          @change="(values) => filters.sort = values[0] || 'recommended'"
          @toggle="handleDropdownToggle"
          @close="handleDropdownClose"
        />

        <button
          type="button"
          class="market-action-pill market-action-text market-action-overflowable"
          @click="openSourceDialog"
        >
          Market 源管理
        </button>

        <button
          type="button"
          class="market-action-icon market-action-overflowable"
          :class="{ 'is-spinning': refreshing }"
          :disabled="refreshing"
          aria-label="刷新"
          :title="refreshing ? '刷新中…' : '刷新'"
          @click="handleRefresh"
        >
          <svg class="size-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
            <path d="M18 3v4h-4M6 21v-4h4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>

        <button
          v-if="hasUpdatableInstalled"
          type="button"
          class="market-action-pill market-action-update market-action-overflowable"
          :disabled="updating"
          @click="handleUpdateAllInstalled"
        >
          {{ updating ? '更新中…' : `更新 ${updatableInstalledCount}` }}
        </button>

        <div class="market-action-overflow-wrap" :class="{ 'is-forced': searchOpen || filters.search }">
          <button
            type="button"
            class="market-action-icon"
            aria-label="更多页面操作"
            :title="'更多操作'"
            @click.stop="toggleOverflowMenu"
          >
            <svg class="size-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="6" cy="12" r="1.6" fill="currentColor"/>
              <circle cx="12" cy="12" r="1.6" fill="currentColor"/>
              <circle cx="18" cy="12" r="1.6" fill="currentColor"/>
            </svg>
          </button>
          <div v-if="overflowMenuOpen" class="market-more-menu market-overflow-menu" @click.stop>
            <button type="button" class="market-menu-item" @click="closeOverflowMenuAnd(openSourceDialog)">Market 源管理</button>
            <button type="button" class="market-menu-item" :disabled="refreshing" @click="closeOverflowMenuAnd(handleRefresh)">{{ refreshing ? '刷新中…' : '刷新全部' }}</button>
            <button v-if="hasUpdatableInstalled" type="button" class="market-menu-item" :disabled="updating" @click="closeOverflowMenuAnd(handleUpdateAllInstalled)">更新全部 · {{ updatableInstalledCount }}</button>
          </div>
        </div>
      </div>
    </section>

    <p v-if="error" class="mb-4 rounded-[14px] border border-red-200/60 bg-red-50/80 px-4 py-3 text-sm text-red-600 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-300">{{ error }}</p>

    <section v-if="loading" class="market-grid">
      <div v-for="i in 6" :key="i" class="market-card-skeleton"></div>
    </section>

    <section v-else-if="filteredPackages.length" class="market-grid">
      <article
        v-for="pkg in filteredPackages"
        :key="pkg.id"
        class="market-card group"
        :class="{ 'market-card-selected': selectedPackage?.id === pkg.id && drawerOpen }"
      >
        <div
          class="market-card-body"
          tabindex="0"
          role="button"
          :aria-label="`查看 ${pkg.name} 详情`"
          @click="openDetail(pkg, $event)"
          @keydown.enter="openDetail(pkg, $event)"
          @keydown.space.prevent="openDetail(pkg, $event)"
        >
          <div class="market-card-head">
            <span class="market-region-badge" :class="isPluginPackage(pkg) ? 'market-region-violet' : regionBadgeClass(pkg)">
              {{ isPluginPackage(pkg) ? 'P' : regionBadge(pkg) }}
            </span>
            <div class="min-w-0 flex-1">
              <h2 class="truncate text-[15px] font-semibold leading-snug text-[var(--text-primary)]">{{ pkg.name }}</h2>
              <p class="mt-1 truncate text-[13px] text-[var(--text-secondary)]">{{ isPluginPackage(pkg) ? pluginIdentity(pkg) : displayMeta(pkg) }}</p>
            </div>
          </div>

          <AdaptiveTagList
            class="market-card-tags"
            :items="isPluginPackage(pkg) ? pluginTagItems(pkg) : displayTagItems(pkg)"
            :max-rows="2"
            :gap="6"
          >
            <template #tag="{ item }">
              <span class="market-tag" :class="item.accentClass">{{ item.label }}</span>
            </template>
            <template #more="{ count }">
              <span class="market-tag market-tag-rest">+{{ count }}</span>
            </template>
          </AdaptiveTagList>
        </div>

        <div class="market-card-foot">
          <button
            v-if="installState(pkg) === 'unsupported'"
            type="button"
            class="market-btn-status"
            disabled
            @click.stop
          >
            {{ pkg.unsupported_reason || '暂不支持' }}
          </button>
          <button
            v-else-if="installState(pkg) === 'installed'"
            type="button"
            class="market-btn-status"
            :disabled="importLoading"
            @click.stop="openDetail(pkg)"
          >
            已安装
          </button>
          <template v-else-if="installState(pkg) === 'update'">
            <span class="market-update-tag">有更新</span>
            <button
              type="button"
              class="market-btn-primary"
              :disabled="importLoading || !packageInstallable(pkg)"
              @click.stop="handleReinstall(pkg)"
            >
              {{ importLoading && actingId === pkg.id ? packageActionLabel(pkg, 'updating') : packageActionLabel(pkg, 'update') }}
            </button>
          </template>
          <button
            v-else
            type="button"
            class="market-btn-primary"
            :disabled="importLoading || !packageInstallable(pkg)"
            @click.stop="handleImport(pkg)"
          >
            {{ importLoading && actingId === pkg.id ? packageActionLabel(pkg, 'installing') : packageActionLabel(pkg, 'install') }}
          </button>

          <div class="market-more-wrap">
            <button
              type="button"
              class="market-more-btn"
              aria-label="更多操作"
              @click.stop="toggleMenu(pkg.id)"
            >
              <svg class="size-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="6" cy="12" r="1.5" fill="currentColor"/>
                <circle cx="12" cy="12" r="1.5" fill="currentColor"/>
                <circle cx="18" cy="12" r="1.5" fill="currentColor"/>
              </svg>
            </button>
            <div v-if="menuOpenId === pkg.id" class="market-more-menu" @click.stop>
              <button v-if="pkg.previewable && !isPluginPackage(pkg)" type="button" class="market-menu-item" @click="closeMenuAnd(() => openDetail(pkg, { showAllChannels: true }))">查看频道列表</button>
              <button v-if="pkg.installed" type="button" class="market-menu-item" :disabled="importLoading" @click="closeMenuAnd(() => handleUninstall(pkg))">{{ packageActionLabel(pkg, 'uninstall') }}</button>
              <button v-if="pkg.installed && pkg.update_available" type="button" class="market-menu-item" :disabled="importLoading" @click="closeMenuAnd(() => handleReinstall(pkg))">立即更新</button>
            </div>
          </div>
        </div>
      </article>
    </section>

    <section v-else class="py-20 text-center">
      <p class="mb-2 text-[15px] font-medium text-[var(--text-primary)]">{{ packageType === 'plugins' ? '没有找到符合条件的 Plugin Package' : '没有找到符合条件的频道包' }}</p>
      <p class="text-[13px] text-[var(--text-secondary)]">试试减少筛选条件或更换关键词。</p>
      <button v-if="hasActiveSelections || filters.search" type="button" class="mx-auto mt-4 market-btn-ghost" @click="clearAllFilters">
        清除筛选
      </button>
    </section>
  </main>

  <Teleport to="body">
    <transition name="market-drawer">
      <div v-if="drawerOpen" class="market-drawer-layer">
        <div class="market-drawer-backdrop" @click="closeDialog"></div>
        <aside
          ref="drawerRef"
          class="market-drawer-pane"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="drawerTitleId"
          tabindex="-1"
          @keydown.tab="onDrawerTab"
        >
          <header class="market-drawer-header">
            <span class="market-region-badge" :class="isPluginPackage(selectedPackage) ? 'market-region-violet' : regionBadgeClass(selectedPackage || {})">
              {{ isPluginPackage(selectedPackage) ? 'P' : regionBadge(selectedPackage || {}) }}
            </span>
            <div class="min-w-0 flex-1">
              <h2 :id="drawerTitleId" class="truncate text-[16px] font-semibold leading-snug text-[var(--text-primary)]">{{ selectedPackage?.name }}</h2>
              <p class="mt-0.5 truncate text-[12.5px] text-[var(--text-secondary)]">{{ isPluginPackage(selectedPackage) ? pluginIdentity(selectedPackage) : displayMeta(selectedPackage || {}) }}</p>
            </div>
            <button type="button" class="market-touch-icon-btn" aria-label="关闭" @click="closeDialog">
              <svg class="size-4" viewBox="0 0 24 24" fill="none"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>
            </button>
          </header>

          <div class="market-drawer-body">
            <section class="market-drawer-section">
              <h3 class="market-section-title">可用性</h3>
              <p class="text-[13.5px] font-medium text-[var(--text-primary)]">{{ availabilitySummary.headline }}</p>
              <p v-if="availabilitySummary.detail" class="mt-1 text-[12.5px] leading-5 text-[var(--text-secondary)]">{{ availabilitySummary.detail }}</p>
            </section>

            <section v-if="!isPluginPackage(selectedPackage) && (drawerTags.length || selectedPackage?.previewable)" ref="channelSectionRef" class="market-drawer-section">
              <h3 class="market-section-title">频道</h3>
              <div v-if="drawerTags.length" class="mb-3 flex flex-wrap gap-1.5">
                <span v-for="tag in drawerTags" :key="tag" class="market-tag" :class="tagAccentClass(tag, selectedPackage || {})">{{ tag }}</span>
              </div>

              <div v-if="previewLoading" class="text-[12.5px] text-[var(--text-secondary)]">正在读取频道…</div>
              <ul
                v-else-if="visibleChannelItems.length"
                class="market-channel-list space-y-1.5"
                :class="{ 'market-channel-list--expanded': showAllChannels }"
              >
                <li v-for="ch in visibleChannelItems" :key="ch.key" class="flex items-center gap-2 text-[13px] text-[var(--text-primary)]">
                  <svg class="size-3.5 shrink-0 text-[var(--text-tertiary)]" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <rect x="4" y="6" width="16" height="12" rx="2" stroke="currentColor" stroke-width="1.6"/>
                    <path d="M9 3.5 12 6l3-2.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
                  </svg>
                  <span class="truncate">{{ ch.name }}</span>
                </li>
              </ul>
              <p v-else-if="previewError" class="text-[12.5px] leading-5 text-[var(--text-secondary)]">暂时无法获取频道列表</p>
              <p v-else class="text-[12.5px] leading-5 text-[var(--text-secondary)]">暂无可展示的频道</p>

              <button
                v-if="!previewLoading && !previewError && totalChannelCount > 0 && selectedPackage?.previewable"
                type="button"
                class="mt-2 inline-flex items-center gap-1 text-[12.5px] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                @click="toggleAllChannels"
              >
                {{ allChannelsToggleLabel }}
              </button>
            </section>

            <section v-if="!isPluginPackage(selectedPackage)" class="market-drawer-section">
              <h3 class="market-section-title">播放方式</h3>
              <dl class="grid grid-cols-[96px_minmax(0,1fr)] gap-y-1.5 text-[13px]">
                <template v-for="row in playbackMethods" :key="row.key">
                  <dt class="text-[var(--text-tertiary)]">{{ row.label }}</dt>
                  <dd :class="row.warn ? 'text-amber-600 dark:text-amber-300' : 'text-[var(--text-primary)]'">{{ row.value }}</dd>
                </template>
              </dl>
            </section>

            <section v-if="isPluginPackage(selectedPackage)" class="market-drawer-section">
              <h3 class="market-section-title">Capability</h3>
              <dl class="grid grid-cols-[96px_minmax(0,1fr)] gap-y-1.5 text-[13px]"><dt class="text-[var(--text-tertiary)]">Contracts</dt><dd class="text-[var(--text-primary)]">{{ providerContractLabels(selectedPackage).join(', ') || '无' }}</dd><dt class="text-[var(--text-tertiary)]">Schemes</dt><dd class="text-[var(--text-primary)]">{{ selectedPackage?.plugin?.owned_schemes?.join(', ') || '无' }}</dd></dl>
            </section>

            <section v-if="isPluginPackage(selectedPackage)" class="market-drawer-section">
              <h3 class="market-section-title">Dependencies</h3>
              <p v-if="!pluginDependencies(selectedPackage).length" class="text-[13px] text-[var(--text-secondary)]">无额外 Python dependency</p>
              <ul v-else class="space-y-1.5 text-[13px]"><li v-for="dependency in pluginDependencies(selectedPackage).slice(0, 8)" :key="`${dependency.name}-${dependency.version}`" class="flex items-center justify-between gap-3"><span class="truncate text-[var(--text-primary)]">{{ dependency.name }}</span><span class="shrink-0 text-[12px] text-[var(--text-tertiary)]">{{ dependency.version }}</span></li></ul>
            </section>

            <section v-if="isPluginPackage(selectedPackage)" class="market-drawer-section">
              <h3 class="market-section-title">Runtime 与权限</h3>
                <dl class="grid grid-cols-[96px_minmax(0,1fr)] gap-y-1.5 text-[13px]"><dt class="text-[var(--text-tertiary)]">Runtime</dt><dd class="text-[var(--text-primary)]">{{ pluginRuntimeLabel(selectedPackage) }}</dd><dt class="text-[var(--text-tertiary)]">Permissions</dt><dd class="text-[var(--text-primary)]">{{ requestedPermissions(selectedPackage).map(permissionLabel).join(', ') || '无额外权限' }}</dd><dt class="text-[var(--text-tertiary)]">Publisher</dt><dd class="text-[var(--text-primary)]">{{ selectedPackage?.plugin?.publisher_id || 'unknown' }}</dd><dt class="text-[var(--text-tertiary)]">Trust</dt><dd class="text-[var(--text-primary)]">{{ selectedPackage?.installed_trust_state || '安装时验证 publisher 与签名' }}</dd></dl>
            </section>

            <section class="market-drawer-section">
              <h3 class="market-section-title">详细信息</h3>
              <dl class="grid grid-cols-[88px_minmax(0,1fr)] gap-y-1.5 text-[13px]">
                <dt class="text-[var(--text-tertiary)]">最近更新</dt>
                <dd class="text-[var(--text-primary)]">{{ relativeUpdatedAt }}</dd>
                <dt class="text-[var(--text-tertiary)]">数据来源</dt>
                <dd class="truncate text-[var(--text-primary)]">{{ selectedPackage?.market_source?.name || selectedPackage?.source_origin || 'unknown' }}</dd>
                <dt class="text-[var(--text-tertiary)]">风险等级</dt>
                <dd class="text-[var(--text-primary)]">{{ riskLabel(selectedPackage?.risk_level) }}</dd>
                <dt class="text-[var(--text-tertiary)]">支持 V1</dt>
                <dd class="text-[var(--text-primary)]">{{ selectedPackage?.supported_in_v1 ? '是' : '否' }}</dd>
                <dt class="text-[var(--text-tertiary)]">版本</dt>
                <dd class="truncate text-[var(--text-primary)]">{{ selectedPackage?.version || '未知' }}</dd>
                <template v-if="selectedPackage?.installed_version"><dt class="text-[var(--text-tertiary)]">已安装版本</dt><dd class="truncate text-[var(--text-primary)]">{{ selectedPackage.installed_version }}</dd></template>
                <dt class="text-[var(--text-tertiary)]">Manifest</dt>
                <dd class="min-w-0">
                  <span class="block truncate text-[12px] text-[var(--text-secondary)]" :title="selectedPackage?.manifest_url || '内联配置'">
                    {{ selectedPackage?.manifest_url || '内联配置' }}
                  </span>
                </dd>
              </dl>
            </section>

            <section v-if="selectedPackage?.installed && !isPluginPackage(selectedPackage)" class="market-drawer-section">
              <label class="flex items-start justify-between gap-3 text-[13px] text-[var(--text-primary)]">
                <span class="min-w-0">
                  <span class="block font-medium">自动更新</span>
                  <span class="mt-0.5 block text-[12px] leading-5 text-[var(--text-secondary)]">用于后续后台自动更新，手动更新和全部更新不受此开关限制</span>
                </span>
                <input
                  :checked="selectedPackage.auto_update"
                  type="checkbox"
                  class="mt-1 size-4 shrink-0 rounded accent-neutral-950 dark:accent-white"
                  :disabled="installConfigLoading"
                  @change="handleAutoUpdateChange(selectedPackage, $event)"
                />
              </label>
            </section>

            <p v-if="selectedPackage?.schema_warnings?.length" class="market-drawer-section text-[12.5px] leading-5 text-amber-600 dark:text-amber-300">
              <span v-for="(item, i) in selectedPackage.schema_warnings.slice(0, 4)" :key="i" class="block">{{ item }}</span>
            </p>
          </div>

          <footer class="market-drawer-footer">
            <div class="min-w-0 flex-1 text-[12.5px] text-[var(--text-secondary)]">
              <template v-if="installState(selectedPackage || {}) === 'update'">发现新版本</template>
              <template v-else-if="installState(selectedPackage || {}) === 'installed'">已安装</template>
              <template v-else-if="installState(selectedPackage || {}) === 'unsupported'">{{ selectedPackage?.unsupported_reason || '暂不支持' }}</template>
              <template v-else>{{ isPluginPackage(selectedPackage) ? '可安装 Plugin Package' : `${selectedPackage?.channel_count || 0} 个频道` }}</template>
            </div>
            <button
              v-if="installState(selectedPackage || {}) === 'unsupported'"
              type="button"
              class="market-btn-primary"
              disabled
            >
              暂不支持
            </button>
            <button
              v-else-if="installState(selectedPackage || {}) === 'update'"
              type="button"
              class="market-btn-primary"
              :disabled="importLoading || !packageInstallable(selectedPackage)"
              @click="handleReinstall(selectedPackage)"
            >
              {{ importLoading ? packageActionLabel(selectedPackage, 'updating') : packageActionLabel(selectedPackage, 'update') }}
            </button>
            <button
              v-else-if="installState(selectedPackage || {}) === 'installed'"
              type="button"
              class="market-btn-ghost"
              :disabled="refreshing"
              @click="handleCheckUpdate"
            >
              检查更新
            </button>
            <button
              v-else
              type="button"
              class="market-btn-primary"
              :disabled="importLoading || !packageInstallable(selectedPackage)"
              @click="handleImport(selectedPackage)"
            >
              {{ importLoading ? packageActionLabel(selectedPackage, 'installing') : packageActionLabel(selectedPackage, 'install') }}
            </button>
            <div v-if="selectedPackage?.installed" class="market-detail-more-wrap">
              <button
                type="button"
                class="market-more-btn"
                aria-label="更多详情操作"
                @click.stop="toggleMenu(`detail-${selectedPackage.id}`)"
              >
                <svg class="size-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <circle cx="6" cy="12" r="1.5" fill="currentColor"/>
                  <circle cx="12" cy="12" r="1.5" fill="currentColor"/>
                  <circle cx="18" cy="12" r="1.5" fill="currentColor"/>
                </svg>
              </button>
              <div v-if="menuOpenId === `detail-${selectedPackage.id}`" class="market-more-menu market-detail-menu" @click.stop>
                <button type="button" class="market-menu-item" :disabled="importLoading" @click="closeMenuAnd(() => handleUninstall(selectedPackage))">{{ packageActionLabel(selectedPackage, 'uninstall') }}</button>
              </div>
            </div>
          </footer>
        </aside>
      </div>
    </transition>
  </Teleport>

  <Teleport to="body">
    <!-- 移动端筛选面板 -->
    <transition name="market-sheet">
      <div
        v-if="filterSheetOpen"
        class="market-sheet-layer"
        @click.self="filterSheetOpen = false"
      >
        <section class="market-filter-sheet">
          <header class="market-sheet-header">
            <div>
              <h2 class="text-[17px] font-semibold text-[var(--text-primary)]">筛选{{ packageType === 'plugins' ? ' Plugin Packages' : '频道包' }}</h2>
              <p class="mt-0.5 text-[12.5px] text-[var(--text-secondary)]">{{ selectedChips.length ? `已选 ${selectedChips.length} 项` : packageType === 'plugins' ? '按状态筛选插件包' : '按地区、运营商和内容整理' }}</p>
            </div>
            <button type="button" class="market-touch-icon-btn" aria-label="关闭筛选" @click="filterSheetOpen = false">
              <svg class="size-4" viewBox="0 0 24 24" fill="none"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>
            </button>
          </header>

          <div class="market-sheet-body">
            <section v-for="group in visibleFilterGroups" :key="group.key" class="market-sheet-group">
              <h3 class="market-section-title">{{ group.label }}</h3>
              <div class="market-sheet-options">
                <button
                  v-for="opt in group.options()"
                  :key="opt.key"
                  type="button"
                  class="market-sheet-option"
                  :class="{ 'is-selected': filterMultiSelections[group.key].includes(opt.key) }"
                  @click="toggleMobileFilterOption(group.key, opt.key)"
                >
                  {{ opt.label }}
                </button>
              </div>
            </section>
          </div>

          <footer class="market-sheet-footer">
            <button type="button" class="market-btn-ghost" :disabled="!hasActiveSelections" @click="clearSelections">清除筛选</button>
            <button type="button" class="market-btn-primary" @click="filterSheetOpen = false">完成</button>
          </footer>
        </section>
      </div>
    </transition>

    <!-- Market 源管理对话框（保持原结构，仅微调样式） -->
    <div
      v-if="sourceDialogOpen"
      class="fixed inset-0 z-[95] flex items-center justify-center bg-neutral-950/35 px-4 py-8 backdrop-blur-md"
      @click.self="closeSourceDialog"
    >
      <section class="max-h-full w-full max-w-3xl overflow-y-auto rounded-[20px] border border-[var(--border)] bg-[var(--bg-soft)] p-6 shadow-2xl shadow-neutral-950/20">
        <div class="mb-5 flex items-start justify-between gap-4">
          <div>
            <h2 class="text-[18px] font-semibold text-[var(--text-primary)]">Market 源管理</h2>
            <!-- <p class="mt-1 text-[12.5px] text-[var(--text-secondary)]">默认启用官方源，也可以添加第三方 Market 同时加载。</p> -->
          </div>
          <button type="button" class="market-icon-btn" aria-label="关闭" @click="closeSourceDialog">
            <svg class="size-4" viewBox="0 0 24 24" fill="none"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>
          </button>
        </div>

        <div class="mb-5 space-y-3">
          <div v-for="source in marketSources" :key="source.id" class="rounded-[14px] border border-[var(--border)] bg-[var(--surface)] p-3">
            <div class="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center">
              <input v-model="source.name" class="market-input sm:w-44" placeholder="名称" />
              <input v-model="source.url" class="market-input min-w-0 flex-1" placeholder="market.json URL" :disabled="source.is_builtin" />
            </div>
            <div class="flex flex-wrap items-center gap-3 text-[12px] text-[var(--text-secondary)]">
              <label class="flex items-center gap-1.5">
                <input v-model="source.enabled" type="checkbox" class="size-3.5 rounded accent-neutral-950 dark:accent-white" />
                启用
              </label>
              <label class="flex items-center gap-1.5">
                <input v-model="source.allow_private" type="checkbox" class="size-3.5 rounded accent-neutral-950 dark:accent-white" />
                允许本机/内网
              </label>
              <span :class="source.last_status === 'error' ? 'text-red-500' : source.last_status === 'ok' ? 'text-emerald-500' : ''">
                {{ sourceStatusLabel(source) }}
              </span>
              <span v-if="source.last_error" class="min-w-0 flex-1 truncate text-red-500">{{ source.last_error }}</span>
              <div class="ml-auto flex gap-2">
                <button type="button" class="market-btn-ghost" :disabled="refreshing" @click="handleRefreshSource(source)">刷新</button>
                <button type="button" class="market-btn-ghost" @click="handleUpdateSource(source)">保存</button>
                <button type="button" class="market-btn-ghost" :disabled="source.is_builtin" @click="handleDeleteSource(source)">删除</button>
              </div>
            </div>
          </div>
        </div>

        <div class="rounded-[14px] border border-[var(--border)] p-3">
          <h3 class="mb-3 text-[14px] font-semibold text-[var(--text-primary)]">添加第三方源</h3>
          <div class="grid gap-2 sm:grid-cols-[160px_minmax(0,1fr)]">
            <input v-model="sourceDraft.name" class="market-input" placeholder="名称" />
            <input v-model="sourceDraft.url" class="market-input" placeholder="https://example.com/market.json" />
          </div>
          <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
            <label class="flex items-center gap-1.5 text-[12px] text-[var(--text-secondary)]">
              <input v-model="sourceDraft.allow_private" type="checkbox" class="size-3.5 rounded accent-neutral-950 dark:accent-white" />
              允许本机/内网 URL
            </label>
            <button type="button" class="market-btn-primary" @click="handleCreateSource">添加源</button>
          </div>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  createMarketSource,
  deleteMarketSource,
  fetchMarketPackages,
  fetchMarketPackage,
  fetchMarketSummary,
  fetchMarketSources,
  importMarketPackage,
  previewMarketPackage,
  refreshMarket,
  refreshMarketSource,
  runMarketUpdates,
  uninstallMarketPackage,
  updateMarketInstall,
  updateMarketPackage,
  updateMarketSource,
} from '../api/market'
import { approvePluginPermission, pluginErrorCode, pluginErrorDetails, pluginErrorMessage } from '../api/plugins'
import { useToastStore } from '../stores/toast'
import MarketFilterDropdown from '../components/MarketFilterDropdown.vue'
import AdaptiveTagList from '../components/AdaptiveTagList.vue'
import { isPluginPackage, packageActionLabel, packageInstallable, permissionLabel, pluginDependencies, pluginIdentity, pluginRuntimeLabel, providerContractLabels, requestedPermissions } from './marketPackageUi'

const toastStore = useToastStore()
const route = useRoute()
const router = useRouter()

const summary = ref({})
const packages = ref([])
const loading = ref(false)
const refreshing = ref(false)
const updating = ref(false)
const previewLoading = ref(false)
const previewError = ref('')
const importLoading = ref(false)
const installConfigLoading = ref(false)
const error = ref('')
const drawerOpen = ref(false)
const sourceDialogOpen = ref(false)
const filterSheetOpen = ref(false)
const selectedPackage = ref(null)
const preview = ref(null)
const marketSources = ref([])
const menuOpenId = ref(null)
const actingId = ref(null)
const searchOpen = ref(false)
const searchInputRef = ref(null)
// 父级集中管理 Dropdown 打开状态，确保任何时间只有一个 Dropdown 展开。
const activeDropdownKey = ref(null)
// 第二行窄桌面时收纳低优先操作的菜单。
const overflowMenuOpen = ref(false)
// Drawer 打开/关闭时保存与恢复焦点、body overflow。
const drawerRef = ref(null)
const detailTriggerElement = ref(null)
const channelSectionRef = ref(null)
const showAllChannels = ref(false)
// 当用户从卡片菜单"查看频道列表"进入时，需要等 preview 完成后再切到展开态，
// 避免先渲染一帧代表频道再跳到完整列表造成闪烁。
const pendingShowAllChannels = ref(false)
let previousBodyOverflow = ''
const drawerTitleId = 'market-drawer-title'
let searchDebounceTimer = null
let loadPackagesRequestId = 0
let previewRequestId = 0
const sourceDraft = reactive({
  name: '',
  url: '',
  allow_private: false,
})
const packageType = ref(route.query.type === 'plugins' ? 'plugins' : 'content')
const packageTypeOptions = Object.freeze([
  { key: 'content', label: '内容' },
  { key: 'plugins', label: 'Plugins' },
])

// 服务器端筛选只透传 search（其余在前端做多选过滤；后端单选 API 不便表达多选）。
const filters = reactive({
  search: '',
  sort: 'recommended',
})

// 多选筛选状态（前端过滤）。
const filterMultiSelections = reactive({
  region: [],
  operator: [],
  kind: [],
  status: [],
  category: [],
})

// ── 维度映射 ─────────────────────────────────────────────────

const KIND_LABELS = {
  playlist: '静态播放列表',
  dynamic_playlist: '动态播放列表',
  mixed: '混合包',
  provider: 'Provider',
  remote_resolver: '远程解析器',
  dynamic_provider: '动态 Provider',
  platform_pack: '平台直播',
  radio_pack: '电台包',
}

const STATUS_LABELS = {
  stable: '稳定',
  experimental: '测试中',
  unstable: '测试中',
  broken: '不可用',
  deprecated: '废弃',
  unknown: '未知',
}

const OPERATOR_LABELS = {
  global: '不限',
  cn: '',
  cmcc: '移动',
  ctcc: '电信',
  cucc: '联通',
  china_mobile: '移动',
  china_telecom: '电信',
  china_unicom: '联通',
  cernet: '教育网',
  broadcast: '广电',
  oversea: '海外',
  unknown: '其他',
}

const OPERATOR_IGNORE_VALUES = new Set(['cn', 'global', 'unknown', ''])

const OPERATOR_ALIAS_LABELS = [
  { pattern: /^(cmcc|china_mobile|中国移动|移动)$/i, label: '移动' },
  { pattern: /^(ctcc|china_telecom|中国电信|电信)$/i, label: '电信' },
  { pattern: /^(cucc|china_unicom|中国联通|联通)$/i, label: '联通' },
  { pattern: /^(broadcast|中国广电|广电)$/i, label: '广电' },
  { pattern: /^(cernet|教育网)$/i, label: '教育网' },
  { pattern: /^(oversea|海外)$/i, label: '海外' },
]

const RISK_LABELS = {
  low: '低',
  medium: '中',
  high: '高',
  unknown: '未知',
}

const DEFAULT_TAG_RULES = {
  '央视': { priority: 100, tone: 'red', aliases: ['cctv', 'cgtn'] },
  '卫视': { priority: 92, aliases: ['satellite'] },
  '本地台': { priority: 88, aliases: ['local'] },
  '本省台': { priority: 86 },
  '体育': { priority: 82, tone: 'blue', aliases: ['sports', 'sport', '赛事'] },
  '足球': { priority: 78, tone: 'blue', aliases: ['football'] },
  '篮球': { priority: 76, tone: 'blue', aliases: ['basketball'] },
  '少儿': { priority: 74, aliases: ['kids', 'kid', 'children'] },
  '动画': { priority: 70, aliases: ['animation', 'cartoon', 'anime'] },
  '电影': { priority: 66, tone: 'orange', aliases: ['movie', 'movies', 'film'] },
  '剧场': { priority: 62, tone: 'orange' },
  '港片': { priority: 60, tone: 'orange' },
  '香港': { priority: 58 },
  '教育': { priority: 54, aliases: ['education'] },
  '新闻': { priority: 50, aliases: ['news'] },
  '纪录': { priority: 46, aliases: ['documentary'] },
  '音乐': { priority: 42, aliases: ['music'] },
  '生活': { priority: 38 },
  '购物': { priority: 34, aliases: ['shopping'] },
  '戏曲': { priority: 30 },
  '国际': { priority: 26 },
  'CETV': { priority: 24 },
  'BesTV': { priority: 22 },
  'CHC': { priority: 20 },
  '电视': { priority: 0, aliases: ['tv'] },
  '直播': { priority: 0, aliases: ['live'] },
}

const USER_TAG_RULES = {}

function mergeTagRules(base, overrides = {}) {
  const merged = {}
  for (const [label, rule] of Object.entries(base)) {
    merged[label] = { ...rule, aliases: [...(rule.aliases || [])] }
  }
  for (const [label, rule] of Object.entries(overrides)) {
    const current = merged[label] || {}
    merged[label] = {
      ...current,
      ...rule,
      aliases: [...(current.aliases || []), ...(rule.aliases || [])],
    }
  }
  return merged
}

const TAG_RULES = mergeTagRules(DEFAULT_TAG_RULES, USER_TAG_RULES)

// 由 (label, rule) -> alias 索引：用于把 alias 归一化回标签。
function buildAliasIndex(rules) {
  const out = {}
  for (const [label, rule] of Object.entries(rules)) {
    out[String(label).toLowerCase().replace(/[\s_-]+/g, '_')] = label
    for (const alias of (rule.aliases || [])) {
      out[String(alias).toLowerCase().replace(/[\s_-]+/g, '_')] = label
    }
  }
  return out
}

const DEFAULT_TAG_ALIAS_LABELS = buildAliasIndex(TAG_RULES)

// Market 协议允许包级 tag tone 枚举。前端再做一次防御性校验：来自第三方源的
// 任意 tone 字符串都必须落在此白名单内。
const ALLOWED_TAG_TONES = new Set(['neutral', 'red', 'blue', 'orange', 'green', 'violet'])

// 单个 pkg 的有效 tag 规则。继承策略由 market_source.tag_definitions_mode 决定：
//
//   inherit (默认) —— Market 源 tag_definitions 叠加在 WaveFlow 内置
//                     DEFAULT_TAG_RULES 之上：源里没声明的标签继续沿用内置
//                     priority / tone / emphasized / aliases。
//   replace        —— 仅使用当前 Market 源显式声明的 tag_definitions；未声明
//                     的标签按中性默认（priority 为 0、无 tone、emphasized=false），
//                     且 alias 索引也只使用源声明，不会让英文别名被映射到
//                     内置中文标签。
//
// 第三方源的规则只能影响自己的包；同一 label 在源中有自定义时，priority / tone /
// emphasized 取源的；inherit 模式下 aliases 与默认值合并去重；replace 模式下
// aliases 仅来自源声明。tone 必须落入受控枚举，否则忽略。
function packageTagRules(pkg) {
  const source = pkg?.market_source || {}
  const mode = source.tag_definitions_mode === 'replace' ? 'replace' : 'inherit'
  const sourceDefs = source.tag_definitions
  const hasSourceDefs = sourceDefs && typeof sourceDefs === 'object' && Object.keys(sourceDefs).length > 0

  if (mode === 'inherit') {
    if (!hasSourceDefs) return TAG_RULES
    const merged = {}
    for (const [label, rule] of Object.entries(TAG_RULES)) {
      merged[label] = { ...rule, aliases: [...(rule.aliases || [])] }
    }
    return _mergeSourceDefsInto(merged, sourceDefs, { keepDefaultAliases: true })
  }

  // replace：忽略 DEFAULT_TAG_RULES，仅使用源自身声明。
  return _mergeSourceDefsInto({}, hasSourceDefs ? sourceDefs : {}, { keepDefaultAliases: false })
}

function _mergeSourceDefsInto(merged, sourceDefs, { keepDefaultAliases }) {
  for (const [label, rule] of Object.entries(sourceDefs)) {
    if (!rule || typeof rule !== 'object') continue
    const current = merged[label] || {}
    const next = { ...current }
    if (typeof rule.priority === 'number' && Number.isFinite(rule.priority)) {
      next.priority = Math.max(0, Math.min(100, rule.priority))
    }
    if (typeof rule.tone === 'string' && ALLOWED_TAG_TONES.has(rule.tone)) {
      next.tone = rule.tone
    }
    if (typeof rule.emphasized === 'boolean') {
      next.emphasized = rule.emphasized
    }
    const aliasArr = Array.isArray(rule.aliases) ? rule.aliases : []
    const cleanAliases = aliasArr.filter(v => typeof v === 'string' && v.trim())
    if (keepDefaultAliases) {
      next.aliases = Array.from(new Set([
        ...(current.aliases || []),
        ...cleanAliases,
      ]))
    } else {
      // replace 模式下不合并默认 aliases。
      next.aliases = cleanAliases
    }
    merged[label] = next
  }
  return merged
}

// 注意：alias 索引按 pkg 重算（normalizeTagLabel 内部完成），
// 否则源自定义的 alias 不会被识别。
// 卡片标签需要排除的"身份信息"（避免与标题/Meta 重复）。
const IDENTITY_EXCLUDE_PATTERNS = [
  /^IPTV$/i,
  /^HLS$/i,
  /^HTTP[S]?$/i,
  /^M3U[8]?$/i,
  /^TV$/i, /^Live$/i,
  /^单播$/, /^组播$/, /^直播$/, /^播放列表$/, /^电视$/,
  /^移动$/, /^联通$/, /^电信$/, /^广电$/, /^教育网$/, /^海外$/,
  /^cmcc$/i, /^ctcc$/i, /^cucc$/i, /^cernet$/i, /^broadcast$/i, /^oversea$/i, /^global$/i, /^cn$/i,
  /^playlist$/i, /^dynamic_playlist$/i, /^provider$/i, /^remote_resolver$/i, /^dynamic_provider$/i,
  /^platform_pack$/i, /^radio_pack$/i, /^mixed$/i,
]

const PROVINCE_BADGES = {
  '北京': '京', '上海': '沪', '天津': '津', '重庆': '渝',
  '黑龙江': '黑', '吉林': '吉', '辽宁': '辽',
  '河北': '冀', '河南': '豫', '山东': '鲁', '山西': '晋',
  '陕西': '陕', '甘肃': '甘', '宁夏': '宁', '青海': '青',
  '新疆': '新', '内蒙古': '蒙', '西藏': '藏',
  '四川': '川', '贵州': '贵', '云南': '云',
  '湖北': '鄂', '湖南': '湘', '江苏': '苏', '浙江': '浙', '安徽': '皖',
  '江西': '赣', '福建': '闽', '广东': '粤', '广西': '桂', '海南': '琼',
  '香港': '港', '澳门': '澳', '台湾': '台',
}

// 区域徽章背景色 hash，避免每个区域都用同色，但保持低饱和。
const REGION_PALETTE = [
  'market-region-rose',
  'market-region-sky',
  'market-region-emerald',
  'market-region-orange',
]

// Market 协议允许包级显式声明的徽章 tone 集合。tone → CSS class 一一映射。
// 与后端 BADGE_TONES 一致；前端不接受任何不在此集合内的值。
const BADGE_TONE_CLASS = {
  neutral: 'market-region-neutral',
  rose: 'market-region-rose',
  sky: 'market-region-sky',
  emerald: 'market-region-emerald',
  orange: 'market-region-orange',
  violet: 'market-region-violet',
}

function hashIndex(str, mod) {
  let h = 0
  const s = String(str || '')
  for (let i = 0; i < s.length; i += 1) {
    h = (h * 31 + s.charCodeAt(i)) >>> 0
  }
  return h % mod
}

// 自动推导徽章文本：基于 region/country/品牌识别。
function autoBadgeText(pkg) {
  const province = String(pkg?.region?.province || '').trim()
  const country = String(pkg?.region?.country || '').trim()
  const identity = `${pkg?.name || ''} ${pkg?.id || ''} ${pkg?.source_origin || ''}`.toLowerCase()
  if (identity.includes('youtube') || identity.includes('yt_')) return 'YT'
  if (identity.includes('waveflow')) return 'W'
  if (province) {
    for (const [key, badge] of Object.entries(PROVINCE_BADGES)) {
      if (province.includes(key)) return badge
    }
    if (/global|world|unknown/i.test(province)) return '全'
    if (/^[a-z]/i.test(province)) return '全'
    return province.slice(0, 1)
  }
  if (country) {
    if (/global|world|unknown/i.test(country)) return '全'
    if (country.includes('中国')) return '中'
    if (/^[a-z]/i.test(country)) return '全'
    return country.slice(0, 1)
  }
  return '全'
}

function autoBadgeToneClass(pkg) {
  const seed = String(pkg?.region?.province || pkg?.region?.country || pkg?.id || 'x')
  return REGION_PALETTE[hashIndex(seed, REGION_PALETTE.length)]
}

// 解析包级 display.badge 的合法配置（受控；后端已经 sanitized，前端再做一次防御性校验）。
function packageBadgeOverride(pkg) {
  const raw = pkg?.display?.badge
  if (!raw || typeof raw !== 'object') return null
  const text = typeof raw.text === 'string' ? raw.text.trim().slice(0, 3) : ''
  const tone = typeof raw.tone === 'string' && BADGE_TONE_CLASS[raw.tone] ? raw.tone : ''
  if (!text && !tone) return null
  return { text, tone }
}

// 单一入口：返回 { text, toneClass }，模板/列表统一调用。优先级：
//   package.display.badge → 内置品牌 / 省份 / 国家识别 → 稳定 hash 调色板。
function effectiveBadge(pkg) {
  const override = packageBadgeOverride(pkg)
  const text = override?.text || autoBadgeText(pkg)
  const toneClass = override?.tone
    ? BADGE_TONE_CLASS[override.tone]
    : autoBadgeToneClass(pkg)
  return { text, toneClass }
}

function regionBadge(pkg) { return effectiveBadge(pkg).text }
function regionBadgeClass(pkg) { return effectiveBadge(pkg).toneClass }

function kindLabel(kind) { return KIND_LABELS[kind] || kind || '未知' }
function statusLabel(status) { return STATUS_LABELS[status] || status || '未知' }
function riskLabel(level) { return RISK_LABELS[level] || level || '未知' }

function normalizeOperatorLabel(value) {
  const raw = String(value || '').trim()
  const key = raw.toLowerCase()
  if (OPERATOR_IGNORE_VALUES.has(key)) return ''
  if (Object.prototype.hasOwnProperty.call(OPERATOR_LABELS, key)) return OPERATOR_LABELS[key]
  for (const rule of OPERATOR_ALIAS_LABELS) {
    if (rule.pattern.test(raw)) return rule.label
  }
  return raw
}

function operatorLabels(pkg) {
  const seen = new Set()
  const out = []
  for (const raw of (pkg?.operators || [])) {
    const label = normalizeOperatorLabel(raw)
    if (!label || seen.has(label)) continue
    seen.add(label)
    out.push(label)
  }
  return out
}

function provinceOf(pkg) {
  const value = String(pkg?.region?.province || '').trim()
  return /^(global|world|unknown)$/i.test(value) ? '' : value
}

function countryOf(pkg) {
  const value = String(pkg?.region?.country || '').trim()
  return /^(global|world|unknown)$/i.test(value) ? '' : value
}

function normalizeTagLabel(value, pkg) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const key = raw.toLowerCase().replace(/[\s_-]+/g, '_')
  // alias 解析受当前包所属源的模式控制：
  //   inherit —— 先查源合并索引，再回退到 DEFAULT_TAG_ALIAS_LABELS；
  //   replace —— 仅查源自身索引，不能让英文别名被映射到内置中文标签。
  const mode = pkg?.market_source?.tag_definitions_mode === 'replace' ? 'replace' : 'inherit'
  if (pkg) {
    const rules = packageTagRules(pkg)
    if (rules !== TAG_RULES) {
      const idx = buildAliasIndex(rules)
      if (idx[key]) return idx[key]
    }
  }
  if (mode === 'replace') return raw
  return DEFAULT_TAG_ALIAS_LABELS[key] || raw
}

// ── displayMeta / displayTags ─────────────────────────────────

function displayMeta(pkg) {
  if (!pkg) return ''
  const parts = []
  if (pkg.channel_count) parts.push(`${pkg.channel_count} 个频道`)
  const operators = operatorLabels(pkg)
  const province = provinceOf(pkg)
  const country = countryOf(pkg)
  // "安徽移动" 这种地区+运营商紧贴写法更像直播频道页的内容描述。
  if (province && operators.length) {
    parts.push(`${province}${operators[0]}`)
  } else if (province) {
    parts.push(province)
  } else if (country) {
    parts.push(country)
  } else if (operators.length) {
    parts.push(operators[0])
  }
  parts.push(deliveryLabel(pkg))
  return parts.filter(Boolean).join(' · ')
}

function deliveryLabel(pkg) {
  const structured = [
    pkg?.delivery,
    pkg?.transport,
    pkg?.mode,
    pkg?.manifest?.delivery,
    pkg?.manifest?.transport,
    pkg?.manifest?.mode,
  ].map(v => String(v || '').trim()).find(Boolean)
  const normalized = normalizeDeliveryToken(structured)
  if (normalized) return normalized

  const tokens = [...(pkg?.tags || []), ...(pkg?.categories || [])].map(v => String(v || '').trim())
  if (tokens.some(v => /^组播$/i.test(v) || /multicast|igmp|rtp/i.test(v))) return '组播'
  if (tokens.some(v => /^单播$/i.test(v) || /unicast|hls|m3u8|http/i.test(v))) return '单播'
  if (/dynamic/i.test(String(pkg?.kind || ''))) return '动态包'
  return kindLabel(pkg?.kind)
}

function normalizeDeliveryToken(value) {
  const v = String(value || '').trim()
  if (!v) return ''
  if (/^(unicast|single|http|hls|m3u8|单播)$/i.test(v)) return '单播'
  if (/^(multicast|igmp|rtp|udp|组播)$/i.test(v)) return '组播'
  if (/^(dynamic|dynamic_playlist|动态|动态包)$/i.test(v)) return '动态包'
  return ''
}

function isIdentityToken(value, pkg) {
  const v = String(value || '').trim()
  if (!v) return true
  for (const pattern of IDENTITY_EXCLUDE_PATTERNS) {
    if (pattern.test(v)) return true
  }
  // 重复地区/运营商身份：和当前 pkg 完全一致的省份/运营商
  const province = provinceOf(pkg)
  const country = countryOf(pkg)
  if (province && v === province) return true
  if (country && v === country) return true
  if (operatorLabels(pkg).includes(v)) return true
  if (kindLabel(pkg?.kind) === v) return true
  return false
}

function categoryRank(value, pkg) {
  const label = normalizeTagLabel(value, pkg)
  const rules = packageTagRules(pkg)
  const direct = rules[label]
  if (direct && typeof direct.priority === 'number') return -direct.priority
  // 仅 inherit 模式允许子串包含匹配；replace 模式必须精确命中（alias 在
  // normalizeTagLabel 阶段已经被还原为主标签），未命中则按 priority 0 处理。
  if (tagModeOf(pkg) === 'inherit') {
    for (const [name, rule] of Object.entries(rules)) {
      if (typeof rule.priority !== 'number') continue
      if (String(label).includes(name)) return -rule.priority
    }
  }
  // 未配置任何规则的标签视为 priority 0（与 replace 模式约定一致），
  // 配合 pkgContentTags 中的 originalIndex 保持稳定原始顺序。
  return 0
}

function pkgContentTags(pkg) {
  const seen = new Set()
  const tags = []
  // 优先用 categories，再 fallback 到 tags。
  const candidates = [...(pkg?.categories || []), ...(pkg?.tags || [])]
  for (const raw of candidates) {
    const v = normalizeTagLabel(raw, pkg)
    if (!v) continue
    if (seen.has(v)) continue
    if (isIdentityToken(v, pkg)) continue
    seen.add(v)
    tags.push({ label: v, originalIndex: tags.length })
  }
  // 稳定排序：priority 高的先（categoryRank 返回 -priority），相同 priority
  // 时保持原始数组顺序（不依赖 Array.sort 在不同引擎下的稳定性，显式比较 originalIndex）。
  tags.sort((a, b) => {
    const ra = categoryRank(a.label, pkg)
    const rb = categoryRank(b.label, pkg)
    if (ra !== rb) return ra - rb
    return a.originalIndex - b.originalIndex
  })
  return tags.map(t => t.label)
}

// 卡片标签条目（label + tone class）。返回完整列表——可见数量与 +N 由
// AdaptiveTagList 基于两行真实宽度测量决定，组件外部不再做硬编码 slice。
// 强调色名额仍然限制为 3：tone 必须存在且不是 'neutral'，emphasized=false 不计入。
function displayTagItems(pkg) {
  const tags = pkgContentTags(pkg)
  const rules = packageTagRules(pkg)
  const allowSubstring = tagModeOf(pkg) === 'inherit'
  let accentCount = 0
  return tags.map((label) => {
    const rule = directRule(rules, label, { allowSubstring })
    const tone = rule?.tone
    const emphasized = rule?.emphasized !== false
    const canAccent = Boolean(tone) && tone !== 'neutral' && emphasized && accentCount < 3
    if (canAccent) accentCount += 1
    return {
      label,
      accentClass: canAccent ? `market-tag-${tone}` : '',
    }
  })
}

// 从规则集合中查 label 的有效规则。
//   inherit 模式：精确名称命中失败时回退到子串包含匹配，复用历史宽松行为以兼容
//                 既有显示效果（如"体育新闻" → 命中"体育"）。
//   replace 模式：只允许精确名称命中。alias 已在 normalizeTagLabel 阶段把别名映射
//                 回了主标签，因此精确命中等价于"精确名称 + 该定义声明的 alias"。
//                 子串包含会让源作者声明"体育"后意外把"体育新闻"/"地方体育频道"
//                 也染色，违反 replace 的"只使用源明确提供的规则"含义，禁掉。
function directRule(rules, label, { allowSubstring = true } = {}) {
  if (rules[label]) return rules[label]
  if (!allowSubstring) return null
  for (const [name, rule] of Object.entries(rules)) {
    if (String(label).includes(name)) return rule
  }
  return null
}

function tagModeOf(pkg) {
  return pkg?.market_source?.tag_definitions_mode === 'replace' ? 'replace' : 'inherit'
}

function tagRuleFor(value, pkg) {
  const label = normalizeTagLabel(value, pkg)
  return directRule(packageTagRules(pkg), label, {
    allowSubstring: tagModeOf(pkg) === 'inherit',
  })
}

// 详情 Drawer 内继续按规则染色（不受卡片三色名额限制）。
function tagAccentClass(tag, pkg) {
  const rule = tagRuleFor(tag, pkg)
  if (!rule || rule.emphasized === false) return ''
  return rule.tone ? `market-tag-${rule.tone}` : ''
}

// ── installState ─────────────────────────────────────────────

function installState(pkg) {
  if (!pkg) return 'available'
  if (!packageInstallable(pkg)) return 'unsupported'
  if (pkg.installed && pkg.update_available) return 'update'
  if (pkg.installed) return 'installed'
  return 'available'
}

// ── 抽屉派生数据 ────────────────────────────────────────────

const drawerTags = computed(() => {
  const pkg = selectedPackage.value
  if (!pkg) return []
  const seen = new Set()
  const indexed = []
  for (const raw of [...(pkg.categories || []), ...(pkg.tags || [])]) {
    const v = normalizeTagLabel(raw, pkg)
    if (!v) continue
    if (seen.has(v)) continue
    if (isIdentityToken(v, pkg)) continue
    seen.add(v)
    indexed.push({ label: v, originalIndex: indexed.length })
  }
  indexed.sort((a, b) => {
    const ra = categoryRank(a.label, pkg)
    const rb = categoryRank(b.label, pkg)
    if (ra !== rb) return ra - rb
    return a.originalIndex - b.originalIndex
  })
  return indexed.map(t => t.label)
})

const availabilitySummary = computed(() => {
  const pkg = selectedPackage.value
  if (!pkg) return { headline: '', detail: '' }

  if (isPluginPackage(pkg)) {
    if (!pkg.plugin_installable) {
      return { headline: '当前平台暂不支持', detail: pkg.unsupported_reason || '此 Plugin Package 没有当前平台可用的 artifact。' }
    }
    if (pkg.installed && pkg.update_available) {
      return { headline: '有可用更新', detail: `已安装 ${pkg.installed_version || '当前版本'}，Market 提供 ${pkg.version || '新版本'}。` }
    }
    if (pkg.installed) {
      return { headline: 'Plugin 已安装', detail: '运行状态、权限和 scheme ownership 请前往 Settings → Plugins 管理。' }
    }
    return { headline: '可以安装', detail: '安装会验证 publisher trust、签名、平台兼容性与所需权限。' }
  }

  // 1) 当前版本不支持 / 不可导入。
  if (!pkg.supported_in_v1 || !pkg.importable) {
    return {
      headline: '当前版本暂不支持',
      detail: pkg.unsupported_reason || '此频道包依赖当前版本尚未提供的播放能力。',
    }
  }

  // 2) 后端代理转发（requires_proxy 表示 WaveFlow 自动通过后端代理转发，
  //    并非要求用户先去设置代理；referer/ua/cookie 由 manifest 携带）。
  if (pkg.requires_proxy) {
    return {
      headline: '需通过代理播放',
      detail: pkg.requires_resolver
        ? 'WaveFlow 将通过后端代理访问源站，并根据播放地址按需调用内置解析器。'
        : '该频道包不能直接连接源站，播放请求将通过 WaveFlow 后端代理转发。',
    }
  }

  // 3) 仅声明 Resolver。Resolver 不强制每条频道使用，仅按 URL scheme 自动识别。
  if (pkg.requires_resolver) {
    return {
      headline: '可直接使用',
      detail: 'WaveFlow 会根据播放地址自动识别处理方式，并在需要时调用内置解析器，无需手动配置。',
    }
  }

  // 4) 普通直连。
  const operators = operatorLabels(pkg)
  const region = provinceOf(pkg)
  if (region && operators.length) {
    return {
      headline: '可直接使用',
      detail: `无需代理，播放地址由 WaveFlow 自动识别处理。需要${region}${operators[0]}网络环境。`,
    }
  }
  return { headline: '可直接使用', detail: '无需代理，播放地址由 WaveFlow 自动识别处理。' }
})

// 详情"播放方式"分区：字段名 + 当前处理方式。
// 项目语义审查（backend/market.py）：
//   - requires_proxy → WaveFlow 后端自动代理转发；不要求用户配置代理。
//   - requires_resolver → 按 URL scheme 自动识别，仅在匹配时按需调用内置解析器。
//   - requires_referer / requires_custom_ua → 真实值由 manifest headers 自动携带，
//     用户无需准备；同时强制走后端代理。
//   - requires_cookie → V1 实际是声明类信息：包含 Cookie 的源在 _normalize_source 中
//     已被剥离/标记不可导入。对最终入库可播放的包，Cookie 由 manifest 提供。
const playbackMethods = computed(() => {
  const pkg = selectedPackage.value
  if (!pkg) return []
  return [
    {
      key: 'connection',
      label: '连接方式',
      value: pkg.requires_proxy ? '后端代理转发' : '直接连接',
      warn: false,
    },
    {
      key: 'resolver',
      label: '地址解析',
      value: pkg.requires_resolver ? '自动识别，按需使用内置解析器' : '自动识别',
      warn: false,
    },
    {
      key: 'cookie',
      label: 'Cookie',
      value: pkg.requires_cookie ? '由频道包提供' : '不需要',
      warn: false,
    },
    {
      key: 'referer',
      label: 'Referer',
      value: pkg.requires_referer ? '自动携带' : '不需要',
      warn: false,
    },
    {
      key: 'ua',
      label: 'User-Agent',
      value: pkg.requires_custom_ua ? '频道包指定' : '默认标识',
      warn: false,
    },
  ]
})

const exampleChannels = computed(() => {
  // 优先用已加载的 preview.channels；否则使用 selectedPackage 上预置的 sample_channels（若有）。
  const source = preview.value?.channels || selectedPackage.value?.sample_channels || []
  if (!source.length) return []
  // 按 CCTV/卫视/本地/体育/少儿 优先级取 6 个。
  const named = source.map((ch, idx) => ({
    key: `${ch.name || idx}-${ch.url || idx}`,
    name: String(ch.name || '').trim(),
    group: String(ch.group_name || ch.group || '').trim(),
  })).filter(ch => ch.name)
  const score = (ch) => {
    if (/CCTV|央视/i.test(ch.name)) return 0
    if (/卫视/.test(ch.name)) return 1
    const province = provinceOf(selectedPackage.value || {})
    if (province && ch.name.includes(province)) return 2
    if (/体育/.test(ch.name)) return 3
    if (/少儿|动画|卡通/.test(ch.name)) return 4
    if (/电影|剧场/.test(ch.name)) return 5
    return 9
  }
  named.sort((a, b) => score(a) - score(b))
  return named.slice(0, 6)
})

// 完整频道列表，保留 preview 返回的原始顺序，供"查看全部"展开使用。
const previewChannelItems = computed(() => {
  const source = preview.value?.channels || []
  return source
    .map((ch, idx) => ({
      key: `${ch.name || idx}-${ch.url || idx}-${idx}`,
      name: String(ch.name || '').trim(),
      group: String(ch.group_name || ch.group || '').trim(),
    }))
    .filter(ch => ch.name)
})

const visibleChannelItems = computed(() => (
  showAllChannels.value ? previewChannelItems.value : exampleChannels.value
))

const totalChannelCount = computed(() => {
  return Number(preview.value?.channel_count)
    || previewChannelItems.value.length
    || Number(selectedPackage.value?.channel_count)
    || 0
})

const allChannelsToggleLabel = computed(() => {
  if (showAllChannels.value) return '收起频道'
  if (previewLoading.value && !preview.value) return '正在读取频道…'
  const total = totalChannelCount.value
  return total > 0 ? `查看全部 ${total} 个频道` : '查看全部频道'
})

const relativeUpdatedAt = computed(() => {
  const v = String(selectedPackage.value?.updated_at || '').trim()
  if (!v) return '未知'
  const date = new Date(v.replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return v
  const diff = Date.now() - date.getTime()
  const day = 24 * 60 * 60 * 1000
  if (diff < day) return '今日更新'
  if (diff < 2 * day) return '昨日更新'
  if (diff < 7 * day) return `${Math.floor(diff / day)} 天前`
  if (diff < 30 * day) return `${Math.floor(diff / (7 * day))} 周前`
  if (diff < 365 * day) return `${Math.floor(diff / (30 * day))} 个月前`
  return v.slice(0, 10)
})

// ── 排序 ────────────────────────────────────────────────────

const sortOptions = [
  { key: 'recommended', label: '默认推荐' },
  { key: 'updated', label: '最近更新' },
  { key: 'channels', label: '频道数量' },
  { key: 'name', label: '名称排序' },
]

// ── 筛选选项动态生成 ────────────────────────────────────────

const STATUS_FILTER_KEYS = ['stable', 'experimental', 'unstable', 'broken', 'deprecated', 'available', 'installed', 'update', 'unsupported', 'requires_proxy']

function statusFilterLabel(key) {
  const map = {
    stable: '稳定',
    experimental: '测试中',
    unstable: '测试中',
    broken: '不可用',
    deprecated: '已废弃',
    available: '未安装',
    installed: '已安装',
    update: '有更新',
    unsupported: '暂不支持',
    requires_proxy: '代理播放',
  }
  return map[key] || key
}

function pkgRegionTokens(pkg) {
  const r = pkg?.region || {}
  return [r.country, r.province, r.city].filter(Boolean).map(v => String(v).trim())
}

const filterGroups = [
  {
    key: 'region',
    label: '地区',
    options: () => uniqueValues(packages.value.flatMap(pkgRegionTokens)).map(v => ({ key: v, label: v })),
  },
  {
    key: 'operator',
    label: '运营商',
    options: () => uniqueValues(packages.value.flatMap(operatorLabels)).map(v => ({ key: v, label: v })),
  },
  {
    key: 'kind',
    label: '类型',
    options: () => uniqueValues(packages.value.map(p => p.kind).filter(Boolean)).map(v => ({ key: v, label: kindLabel(v) })),
  },
  {
    key: 'status',
    label: '状态',
    options: () => STATUS_FILTER_KEYS
      .filter(k => filterStatusHasMatch(k))
      .map(k => ({ key: k, label: statusFilterLabel(k) })),
  },
  {
    key: 'category',
    label: '内容标签',
    options: () => uniqueValues(packages.value.flatMap(pkgContentTags)).slice(0, 60).map(v => ({ key: v, label: v })),
  },
]
const visibleFilterGroups = computed(() => packageType.value === 'plugins'
  ? filterGroups.filter(group => group.key === 'status')
  : filterGroups)

function selectPackageType(value) {
  packageType.value = value === 'plugins' ? 'plugins' : 'content'
  clearSelections()
  filters.sort = 'recommended'
  router.replace({ path: '/market', query: packageType.value === 'plugins' ? { type: 'plugins' } : {} })
}

function openQueriedPackage() {
  const packageId = String(route.query.package || '')
  if (!packageId) return
  const pkg = packages.value.find(item => item.id === packageId)
  if (pkg) openDetail(pkg)
}

function filterStatusHasMatch(key) {
  const list = packages.value
  if (!list.length) return true
  return list.some(p => packageMatchesStatusKey(p, key))
}

function packageMatchesStatusKey(pkg, key) {
  switch (key) {
    case 'available': return !pkg.installed && packageInstallable(pkg)
    case 'installed': return !!pkg.installed && !pkg.update_available
    case 'update': return !!pkg.installed && !!pkg.update_available
    case 'unsupported': return !packageInstallable(pkg)
    case 'requires_proxy': return !!pkg.requires_proxy
    default: return pkg.status === key
  }
}

function uniqueValues(items) {
  return Array.from(new Set(items.filter(Boolean).map(v => String(v)))).sort((a, b) => String(a).localeCompare(String(b), 'zh-CN'))
}

function onMultiFilterChange(group, values) {
  filterMultiSelections[group] = Array.isArray(values) ? values.slice() : []
}

const hasActiveSelections = computed(() => {
  return Object.values(filterMultiSelections).some(arr => arr && arr.length)
})

const selectedChips = computed(() => {
  const out = []
  for (const group of visibleFilterGroups.value) {
    const selected = filterMultiSelections[group.key] || []
    if (!selected.length) continue
    const opts = group.options()
    const map = new Map(opts.map(o => [o.key, o.label]))
    for (const v of selected) {
      out.push({ group: group.key, value: v, label: map.get(v) || v })
    }
  }
  return out
})

function removeSelection(group, value) {
  const current = filterMultiSelections[group] || []
  filterMultiSelections[group] = current.filter(v => v !== value)
}

function toggleMobileFilterOption(group, value) {
  const current = new Set(filterMultiSelections[group] || [])
  if (current.has(value)) current.delete(value)
  else current.add(value)
  filterMultiSelections[group] = Array.from(current)
}

function clearSelections() {
  for (const key of Object.keys(filterMultiSelections)) {
    filterMultiSelections[key] = []
  }
}

function clearSearch() {
  filters.search = ''
  searchOpen.value = false
}

function clearAllFilters() {
  clearSelections()
  clearSearch()
}

function toggleStatusShortcut(status) {
  const current = filterMultiSelections.status
  if (current.length === 1 && current[0] === status) {
    filterMultiSelections.status = []
  } else {
    filterMultiSelections.status = [status]
  }
}

const quickFilterTabs = computed(() => [
  {
    key: 'all',
    label: '全部',
    active: () => !hasActiveSelections.value,
    select: () => clearSelections(),
  },
  {
    key: 'installed',
    label: '已安装',
    active: () => filterMultiSelections.status.length === 1 && filterMultiSelections.status[0] === 'installed',
    select: () => toggleStatusShortcut('installed'),
  },
  {
    key: 'update',
    label: '有更新',
    active: () => filterMultiSelections.status.length === 1 && filterMultiSelections.status[0] === 'update',
    select: () => toggleStatusShortcut('update'),
  },
])

function openSearch() {
  searchOpen.value = true
  nextTick(() => searchInputRef.value?.focus())
}

function closeSearch() {
  filters.search = ''
  searchOpen.value = false
}

function handleSearchBlur() {
  if (!filters.search.trim()) searchOpen.value = false
}

// ── 前端筛选 + 排序 ────────────────────────────────────────

const filteredPackages = computed(() => {
  let list = packages.value.filter(pkg => packageType.value === 'plugins' ? isPluginPackage(pkg) : !isPluginPackage(pkg))
  const sel = filterMultiSelections
  if (sel.region.length) {
    list = list.filter(p => {
      const tokens = pkgRegionTokens(p)
      return sel.region.some(v => tokens.includes(v))
    })
  }
  if (sel.operator.length) {
    list = list.filter(p => operatorLabels(p).some(op => sel.operator.includes(op)))
  }
  if (sel.kind.length) {
    list = list.filter(p => sel.kind.includes(p.kind))
  }
  if (sel.status.length) {
    list = list.filter(p => sel.status.some(k => packageMatchesStatusKey(p, k)))
  }
  if (sel.category.length) {
    list = list.filter(p => {
      const set = new Set(pkgContentTags(p))
      return sel.category.some(v => set.has(v))
    })
  }
  switch (filters.sort) {
    case 'updated':
      list.sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')))
      break
    case 'channels':
      list.sort((a, b) => (b.channel_count || 0) - (a.channel_count || 0))
      break
    case 'name':
      list.sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN'))
      break
    default:
      // 默认推荐：已安装/有更新优先，其次稳定，其次频道数。
      list.sort((a, b) => {
        const score = (p) => {
          let s = 0
          if (p.installed && p.update_available) s -= 30
          else if (p.installed) s -= 10
          if (p.status === 'stable') s -= 5
          if (!p.supported_in_v1 || !p.importable) s += 50
          return s
        }
        return score(a) - score(b) || (b.channel_count || 0) - (a.channel_count || 0)
      })
  }
  return list
})

const resultCountLabel = computed(() => {
  const visible = filteredPackages.value.length
  if (filters.search.trim() || hasActiveSelections.value) return `找到 ${visible} 个`
  const total = packages.value.filter(pkg => packageType.value === 'plugins' ? isPluginPackage(pkg) : !isPluginPackage(pkg)).length
  return `共 ${total} 个`
})

const updatableInstalledPackages = computed(() => packages.value.filter(p => (
  (packageType.value === 'plugins' ? isPluginPackage(p) : !isPluginPackage(p))
  && p.installed && p.update_available
)))
const updatableInstalledCount = computed(() => updatableInstalledPackages.value.length)
const hasUpdatableInstalled = computed(() => updatableInstalledCount.value > 0)

// ── 数据加载 ────────────────────────────────────────────────

async function loadSummary() {
  summary.value = await fetchMarketSummary()
  marketSources.value = (summary.value.sources || []).map(source => ({ ...source }))
}

async function loadSources() {
  const data = await fetchMarketSources()
  marketSources.value = (data.sources || []).map(source => ({ ...source }))
}

async function loadPackages() {
  const requestId = ++loadPackagesRequestId
  const showSkeleton = packages.value.length === 0
  if (showSkeleton) loading.value = true
  error.value = ''
  try {
    // 仅 search 透传后端，剩余筛选完全前端化（用户可任意多选组合）。
    const data = await fetchMarketPackages({ search: filters.search.trim() })
    if (requestId !== loadPackagesRequestId) return
    packages.value = data.packages || []
  } catch (e) {
    if (requestId !== loadPackagesRequestId) return
    error.value = e.message || String(e)
    toastStore.error(error.value)
  } finally {
    if (requestId === loadPackagesRequestId) loading.value = false
  }
}

async function handleRefresh() {
  refreshing.value = true
  error.value = ''
  try {
    summary.value = await refreshMarket()
    marketSources.value = (summary.value.sources || []).map(source => ({ ...source }))
    await loadPackages()
    toastStore.success('频道市场已刷新')
  } catch (e) {
    error.value = e.message || String(e)
    toastStore.error(error.value)
  } finally {
    refreshing.value = false
  }
}

async function handleCheckUpdate() {
  if (!selectedPackage.value) return
  refreshing.value = true
  try {
    summary.value = await refreshMarket()
    marketSources.value = (summary.value.sources || []).map(source => ({ ...source }))
    await loadPackages()
    syncSelectedPackageFromList()
    toastStore.info(selectedPackage.value?.update_available ? '发现新版本' : '当前已是最新')
  } catch (e) {
    toastStore.error(e.message || String(e))
  } finally {
    refreshing.value = false
  }
}

async function handleUpdateAllInstalled() {
  updating.value = true
  error.value = ''
  try {
    if (packageType.value === 'plugins') {
      let updatedCount = 0
      let failedCount = 0
      for (const pkg of updatableInstalledPackages.value) {
        try {
          await updateMarketPackage(pkg.id)
          updatedCount += 1
        } catch (caught) {
          failedCount += 1
          if (pluginErrorCode(caught) === 'PERMISSION_APPROVAL_REQUIRED') {
            await confirmPermissionAndRetry(pkg, caught, async () => {
              await updateMarketPackage(pkg.id)
              updatedCount += 1
              failedCount -= 1
            })
          }
        }
      }
      await loadPackages()
      if (failedCount) toastStore.warning(`已更新 ${updatedCount} 个 Plugin，${failedCount} 个失败`)
      else toastStore.success(`已更新 ${updatedCount} 个 Plugin`)
      return
    }
    const result = await runMarketUpdates()
    await loadSummary()
    await loadPackages()
    syncSelectedPackageFromList()
    if (result.failed) {
      toastStore.warning(`已更新 ${result.updated || 0} 个包，${result.failed} 个失败`)
    } else {
      toastStore.success(`已更新 ${result.updated || 0} 个包`)
    }
  } catch (e) {
    error.value = e.message || String(e)
    toastStore.error(error.value)
  } finally {
    updating.value = false
  }
}

function openSourceDialog() {
  sourceDialogOpen.value = true
  loadSources().catch((e) => { toastStore.error(e.message || String(e)) })
}

function closeSourceDialog() {
  sourceDialogOpen.value = false
}

async function handleCreateSource() {
  if (!sourceDraft.url.trim()) {
    toastStore.error('Market 源 URL 不能为空')
    return
  }
  try {
    await createMarketSource({
      name: sourceDraft.name.trim() || '第三方 Market',
      url: sourceDraft.url.trim(),
      enabled: true,
      allow_private: sourceDraft.allow_private,
    })
    sourceDraft.name = ''
    sourceDraft.url = ''
    sourceDraft.allow_private = false
    await loadSources()
    toastStore.success('已添加')
  } catch (e) {
    toastStore.error(e.message || String(e))
  }
}

async function handleUpdateSource(source) {
  try {
    await updateMarketSource(source.id, {
      name: source.name,
      url: source.url,
      enabled: source.enabled,
      allow_private: source.allow_private,
    })
    await loadSources()
    toastStore.success('已保存')
  } catch (e) {
    toastStore.error(e.message || String(e))
  }
}

async function handleDeleteSource(source) {
  if (!source?.id || source.is_builtin) return
  const ok = await toastStore.askConfirm({ message: `确认删除 Market 源「${source.name || source.url}」？`, confirmText: '删除', danger: true })
  if (!ok) return
  try {
    await deleteMarketSource(source.id)
    await loadSources()
    toastStore.success('已删除')
  } catch (e) {
    toastStore.error(e.message || String(e))
  }
}

async function handleRefreshSource(source) {
  if (!source?.id) return
  refreshing.value = true
  try {
    summary.value = await refreshMarketSource(source.id)
    marketSources.value = (summary.value.sources || []).map(item => ({ ...item }))
    await loadPackages()
    toastStore.success('已刷新')
  } catch (e) {
    toastStore.error(e.message || String(e))
  } finally {
    refreshing.value = false
  }
}

function openDetail(pkg, eventOrOpts) {
  // 兼容两种调用：openDetail(pkg, event) 与 openDetail(pkg, { showAllChannels: true })。
  // 前者来自卡片点击，需要保存触发元素以便关闭后还原焦点。后者来自菜单回调，
  // 此时 closeMenuAnd 早已偷走焦点（菜单按钮自身被卸载），因此回退到 activeElement。
  const isEvent = eventOrOpts && typeof eventOrOpts === 'object' && 'currentTarget' in eventOrOpts
  const opts = (eventOrOpts && !isEvent && typeof eventOrOpts === 'object') ? eventOrOpts : {}
  detailTriggerElement.value = (isEvent ? eventOrOpts.currentTarget : null)
    || (typeof document !== 'undefined' ? document.activeElement : null)

  selectedPackage.value = pkg
  preview.value = null
  previewError.value = ''
  previewRequestId += 1
  drawerOpen.value = true
  // 切换包时默认折叠；从菜单"查看频道列表"进入时只把意图记录到 pending，
  // 等 preview 完成后再翻到展开态，避免代表频道先闪一帧再切换。
  showAllChannels.value = false
  pendingShowAllChannels.value = !!opts.showAllChannels

  if (typeof document !== 'undefined') {
    previousBodyOverflow = document.body.style.overflow || ''
    document.body.style.overflow = 'hidden'
  }

  nextTick(() => {
    drawerRef.value?.focus()
  })

  if (pkg?.previewable) {
    loadFullPreview()
  } else if (isPluginPackage(pkg)) {
    loadPluginPackageDetail(pkg)
  } else {
    pendingShowAllChannels.value = false
  }
}

async function loadPluginPackageDetail(pkg) {
  const requestId = ++previewRequestId
  previewLoading.value = true
  try {
    const detail = await fetchMarketPackage(pkg.id)
    if (requestId !== previewRequestId || selectedPackage.value?.id !== pkg.id) return
    selectedPackage.value = { ...selectedPackage.value, ...detail }
  } catch (error) {
    if (requestId !== previewRequestId || selectedPackage.value?.id !== pkg.id) return
    previewError.value = pluginErrorMessage(error, 'Plugin Package 详情加载失败')
  } finally {
    if (requestId === previewRequestId) previewLoading.value = false
  }
}

function closeDialog() {
  drawerOpen.value = false
  selectedPackage.value = null
  preview.value = null
  previewError.value = ''
  previewRequestId += 1
  showAllChannels.value = false
  pendingShowAllChannels.value = false

  if (typeof document !== 'undefined') {
    document.body.style.overflow = previousBodyOverflow
    previousBodyOverflow = ''
  }

  const trigger = detailTriggerElement.value
  detailTriggerElement.value = null
  if (trigger && typeof trigger.focus === 'function') {
    nextTick(() => {
      try { trigger.focus() } catch { /* ignore */ }
    })
  }
}

function scrollChannelSectionIntoView() {
  const el = channelSectionRef.value
  if (!el || typeof el.scrollIntoView !== 'function') return
  try {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch {
    el.scrollIntoView()
  }
}

function toggleAllChannels() {
  if (!preview.value && !previewLoading.value) {
    // 还没加载过 preview（例如 sample_channels 为代表频道），先触发加载再展开。
    loadFullPreview()
  }
  showAllChannels.value = !showAllChannels.value
  if (showAllChannels.value) {
    nextTick(scrollChannelSectionIntoView)
  }
}

function getDrawerFocusables() {
  const root = drawerRef.value
  if (!root) return []
  const selector = [
    'button:not(:disabled)',
    '[href]',
    'input:not(:disabled)',
    'select:not(:disabled)',
    'textarea:not(:disabled)',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',')
  return Array.from(root.querySelectorAll(selector)).filter(el => !el.hasAttribute('disabled'))
}

function onDrawerTab(e) {
  // 简易焦点循环：让 Tab 在 Drawer 内的可聚焦元素之间循环，不跳回背景。
  const items = getDrawerFocusables()
  if (!items.length) {
    e.preventDefault()
    drawerRef.value?.focus()
    return
  }
  const first = items[0]
  const last = items[items.length - 1]
  const active = document.activeElement
  if (e.shiftKey) {
    if (active === first || active === drawerRef.value) {
      e.preventDefault()
      last.focus()
    }
  } else if (active === last) {
    e.preventDefault()
    first.focus()
  }
}

async function loadFullPreview() {
  const pkg = selectedPackage.value
  if (!pkg?.id) return
  if (preview.value) {
    // 已有 preview 数据时（例如重复点击展开），直接消费 pending 意图。
    if (pendingShowAllChannels.value) {
      pendingShowAllChannels.value = false
      showAllChannels.value = true
      nextTick(scrollChannelSectionIntoView)
    }
    return
  }
  const requestId = ++previewRequestId
  previewError.value = ''
  previewLoading.value = true
  try {
    const data = await previewMarketPackage(pkg.id)
    if (requestId !== previewRequestId || selectedPackage.value?.id !== pkg.id) return
    preview.value = data
    // preview 成功后再应用 pending —— 这样模板从 v-if="previewLoading" 直接切到
    // v-else-if="visibleChannelItems.length"，且 visibleChannelItems 已是完整列表，
    // 不会先渲染一帧代表频道。
    if (pendingShowAllChannels.value) {
      pendingShowAllChannels.value = false
      showAllChannels.value = true
      await nextTick()
      scrollChannelSectionIntoView()
    }
  } catch (e) {
    if (requestId !== previewRequestId || selectedPackage.value?.id !== pkg.id) return
    previewError.value = e.message || String(e)
    pendingShowAllChannels.value = false
    toastStore.error(e.message || String(e))
  } finally {
    if (requestId === previewRequestId) previewLoading.value = false
  }
}

function toggleMenu(id) {
  menuOpenId.value = menuOpenId.value === id ? null : id
  overflowMenuOpen.value = false
}

function closeMenuAnd(fn) {
  menuOpenId.value = null
  if (typeof fn === 'function') fn()
}

// ── Dropdown 单开 ─────────────────────────────────────────────
function handleDropdownToggle(key) {
  activeDropdownKey.value = activeDropdownKey.value === key ? null : key
  overflowMenuOpen.value = false
  menuOpenId.value = null
}

function handleDropdownClose(key) {
  if (activeDropdownKey.value === key || key === undefined) {
    activeDropdownKey.value = null
  }
}

function closeAllDropdowns() {
  if (activeDropdownKey.value !== null) activeDropdownKey.value = null
}

// ── 第二行窄桌面 overflow 菜单 ────────────────────────────────
function toggleOverflowMenu() {
  overflowMenuOpen.value = !overflowMenuOpen.value
  menuOpenId.value = null
  activeDropdownKey.value = null
}

function closeOverflowMenuAnd(fn) {
  overflowMenuOpen.value = false
  if (typeof fn === 'function') fn()
}

function onWindowClick() {
  if (menuOpenId.value !== null) menuOpenId.value = null
  if (overflowMenuOpen.value) overflowMenuOpen.value = false
  // activeDropdownKey 由 Dropdown 组件自身的文档点击监听处理（识别其 root + teleported menu）。
}
function onWindowKey(e) {
  if (e.key === 'Escape') {
    if (filterSheetOpen.value) filterSheetOpen.value = false
    else if (overflowMenuOpen.value) overflowMenuOpen.value = false
    else if (activeDropdownKey.value !== null) closeAllDropdowns()
    else if (searchOpen.value || filters.search) closeSearch()
    else if (menuOpenId.value !== null) menuOpenId.value = null
    else if (drawerOpen.value) closeDialog()
  }
}

async function handleImport(pkg) {
  if (!pkg?.id) return
  importLoading.value = true
  actingId.value = pkg.id
  try {
    const result = await importMarketPackage(pkg.id, preview.value?.preview_id || '')
    markPackageInstalled(pkg.id, result.subscription_id, result.active_version)
    if (isPluginPackage(pkg)) {
      toastStore.success('Plugin 已安装，scheme ownership 保持 Legacy')
    } else if (Array.isArray(result.warnings) && result.warnings.length) {
      toastStore.warning(`已导入 ${result.channel_count || 0} 个频道（含 ${result.warnings.length} 条警告）`)
    } else {
      toastStore.success(`已导入 ${result.channel_count || 0} 个频道`)
    }
    if (drawerOpen.value && selectedPackage.value?.id !== pkg.id) {
      // ignore
    }
  } catch (e) {
    if (pluginErrorCode(e) === 'PERMISSION_APPROVAL_REQUIRED') {
      await confirmPermissionAndRetry(pkg, e, () => handleImport(pkg))
    } else {
      toastStore.error(isPluginPackage(pkg) ? pluginErrorMessage(e, 'Plugin 安装失败') : `导入失败：${e.message || String(e)}`)
    }
  } finally {
    importLoading.value = false
    actingId.value = null
  }
}

async function handleReinstall(pkg) {
  if (!pkg?.id) return
  importLoading.value = true
  actingId.value = pkg.id
  try {
    const result = await updateMarketPackage(pkg.id)
    markPackageInstalled(pkg.id, result.subscription_id, result.active_version)
    toastStore.success(isPluginPackage(pkg) ? 'Plugin 已更新' : `已更新 ${result.channel_count || 0} 个频道`)
  } catch (e) {
    if (pluginErrorCode(e) === 'PERMISSION_APPROVAL_REQUIRED') {
      await confirmPermissionAndRetry(pkg, e, () => handleReinstall(pkg))
    } else {
      toastStore.error(isPluginPackage(pkg) ? pluginErrorMessage(e, 'Plugin 更新失败') : `更新失败：${e.message || String(e)}`)
    }
  } finally {
    importLoading.value = false
    actingId.value = null
  }
}

async function handleAutoUpdateChange(pkg, event) {
  if (!pkg?.id) return
  const enabled = Boolean(event?.target?.checked)
  installConfigLoading.value = true
  try {
    const result = await updateMarketInstall(pkg.id, { auto_update: enabled })
    setPackageAutoUpdate(pkg.id, result.auto_update)
  } catch (e) {
    toastStore.error(e.message || String(e))
    if (event?.target) event.target.checked = !enabled
  } finally {
    installConfigLoading.value = false
  }
}

async function handleUninstall(pkg) {
  if (!pkg?.id) return
  // 先关闭任意残留的"更多"菜单（卡片菜单 / 详情 footer 菜单），
  // 避免确认弹窗出现在菜单背后或被 Drawer backdrop blur 影响层级。
  menuOpenId.value = null
  const ok = await toastStore.askConfirm({
    message: isPluginPackage(pkg)
      ? `确认卸载「${pkg.name}」？如果 scheme 仍由该 Plugin 拥有，后端会拒绝并要求先切回 Legacy。`
      : `确认卸载「${pkg.name}」？`,
    confirmText: packageActionLabel(pkg, 'uninstall'), danger: true,
  })
  if (!ok) return
  importLoading.value = true
  actingId.value = pkg.id
  try {
    await uninstallMarketPackage(pkg.id)
    packages.value = packages.value.map(item => item.id === pkg.id
      ? { ...item, installed: false, installed_subscription_id: null, installed_version: '', auto_update: false }
      : item)
    if (selectedPackage.value?.id === pkg.id) {
      selectedPackage.value = { ...selectedPackage.value, installed: false, installed_subscription_id: null, installed_version: '', auto_update: false }
    }
    toastStore.success(isPluginPackage(pkg) ? 'Plugin 已卸载' : '已卸载')
  } catch (e) {
    toastStore.error(isPluginPackage(pkg) ? pluginErrorMessage(e, 'Plugin 卸载失败') : (e.message || String(e)))
  } finally {
    importLoading.value = false
    actingId.value = null
  }
}

function markPackageInstalled(packageId, subscriptionId, activeVersion = '') {
  packages.value = packages.value.map(item => item.id === packageId
    ? { ...item, installed: true, installed_subscription_id: subscriptionId || null, installed_version: activeVersion || item.version || '', update_available: false }
    : item)
  if (selectedPackage.value?.id === packageId) {
    selectedPackage.value = { ...selectedPackage.value, installed: true, installed_subscription_id: subscriptionId || null, installed_version: activeVersion || selectedPackage.value.version || '', update_available: false }
  }
}

async function confirmPermissionAndRetry(pkg, error, retry) {
  const permissions = pluginErrorDetails(error).permissions || ['network.direct']
  const permission = permissions[0]
  const identity = isPluginPackage(pkg)
    ? pluginIdentity(pkg)
    : String(pluginErrorDetails(error).plugin || '')
  if (!identity || !permission) {
    toastStore.error(pluginErrorMessage(error))
    return
  }
  const ok = await toastStore.askConfirm({
    title: '允许高风险权限',
    message: permission === 'network.direct'
      ? `安装所需扩展「${identity}」需要直接访问网络。该请求不经过 Core managed HTTP，Plugin subprocess 也不是强安全沙箱。`
      : `安装所需扩展「${identity}」需要 ${permissionLabel(permission)}。`,
    confirmText: '允许并继续', danger: true,
  })
  if (!ok) return
  try {
    await approvePluginPermission(identity, permission, isPluginPackage(pkg) ? pkg.id : '')
    await retry()
  } catch (caught) {
    toastStore.error(pluginErrorMessage(caught))
  }
}

function pluginTagItems(pkg) {
  return [
    ...providerContractLabels(pkg).map(label => ({ label, accentClass: 'market-tag-blue' })),
    ...(pkg?.plugin?.owned_schemes || []).map(label => ({ label, accentClass: '' })),
    ...requestedPermissions(pkg).map(name => ({
      label: permissionLabel(name),
      accentClass: name === 'network.direct' ? 'market-tag-orange' : '',
    })),
  ]
}

function setPackageAutoUpdate(packageId, autoUpdate) {
  packages.value = packages.value.map(item => item.id === packageId
    ? { ...item, auto_update: Boolean(autoUpdate) }
    : item)
  if (selectedPackage.value?.id === packageId) {
    selectedPackage.value = { ...selectedPackage.value, auto_update: Boolean(autoUpdate) }
  }
}

function syncSelectedPackageFromList() {
  if (!selectedPackage.value?.id) return
  const latest = packages.value.find(item => item.id === selectedPackage.value.id)
  if (latest) selectedPackage.value = { ...selectedPackage.value, ...latest }
}

function sourceStatusLabel(source) {
  if (source.last_status === 'ok') return '已刷新'
  if (source.last_status === 'error') return '刷新失败'
  return source.is_builtin ? '官方默认' : '未刷新'
}

watch(() => filters.search, () => {
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
  searchDebounceTimer = window.setTimeout(() => {
    searchDebounceTimer = null
    loadPackages()
  }, 300)
})

onMounted(async () => {
  await loadSummary().catch((e) => { error.value = e.message || String(e) })
  await loadPackages()
  openQueriedPackage()
  window.addEventListener('click', onWindowClick)
  window.addEventListener('keydown', onWindowKey)
})

onBeforeUnmount(() => {
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
  loadPackagesRequestId += 1
  previewRequestId += 1
  window.removeEventListener('click', onWindowClick)
  window.removeEventListener('keydown', onWindowKey)
  // 即便组件卸载时 Drawer 仍处于打开状态，也要恢复 body overflow，避免页面永久无法滚动。
  if (drawerOpen.value && typeof document !== 'undefined') {
    document.body.style.overflow = previousBodyOverflow
    previousBodyOverflow = ''
  }
})
</script>

<style scoped>
.market-list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.market-list-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}

.market-inline-search {
  position: relative;
  width: 116px;
  height: 40px;
  flex: 0 0 auto;
  /* 与 AppShell 顶栏搜索保持一致：300ms ease-out。 */
  transition: width 300ms cubic-bezier(0, 0, 0.2, 1);
}

.market-inline-search.is-open {
  width: clamp(240px, 26vw, 360px);
}

.market-search-trigger {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 40px;
  opacity: 1;
  transform: translateX(0);
  transition:
    opacity 300ms cubic-bezier(0, 0, 0.2, 1),
    transform 300ms cubic-bezier(0, 0, 0.2, 1);
  pointer-events: auto;
}

.market-inline-search.is-open .market-search-trigger {
  opacity: 0;
  transform: translateX(-6px);
  pointer-events: none;
}

@media (prefers-reduced-motion: reduce) {
  .market-inline-search,
  .market-search-trigger,
  .market-search-field {
    transition: none;
  }
}

.market-action-pill,
.market-filter-pill {
  display: inline-flex;
  height: 40px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface);
  padding: 0 16px;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
  white-space: nowrap;
  transition: background-color 160ms ease, border-color 160ms ease, color 160ms ease;
}

.market-action-pill {
  width: 116px;
}

.market-action-pill:hover:not(:disabled),
.market-filter-pill:hover {
  border-color: var(--border-strong);
  background: var(--surface-hover);
  color: var(--text-primary);
}

.market-action-pill:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* 文本型 pill（如 Market 源管理）：宽度按内容、内边距收紧，颜色继承 .market-action-pill
   的中性默认（var(--text-secondary)），hover 才升级到 primary——与搜索、排序同视觉等级。 */
.market-action-text {
  width: auto;
  padding: 0 14px;
}

.market-action-update {
  width: auto;
  padding: 0 14px;
  border-color: rgba(245, 158, 11, 0.45);
  background: rgba(245, 158, 11, 0.12);
  color: rgb(180 83 9);
}

.market-action-update:hover:not(:disabled) {
  background: rgba(245, 158, 11, 0.18);
  border-color: rgba(245, 158, 11, 0.65);
  color: rgb(180 83 9);
}

.dark .market-action-update {
  border-color: rgba(245, 158, 11, 0.5);
  background: rgba(245, 158, 11, 0.18);
  color: rgb(252 211 77);
}

.dark .market-action-update:hover:not(:disabled) {
  background: rgba(245, 158, 11, 0.26);
  color: rgb(252 211 77);
}

.market-action-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  flex: 0 0 auto;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-secondary);
  transition: background-color 160ms ease, border-color 160ms ease, color 160ms ease;
}

.market-action-icon:hover:not(:disabled) {
  background: var(--surface-hover);
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.market-action-icon:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.market-action-icon.is-spinning svg {
  animation: market-rotate 1s linear infinite;
}

/* ── 第二行窄桌面 overflow 收纳 ─────────────────────────── */
/* 默认（宽屏 ≥1280px）：完整显示 Market 源管理 / 刷新 / 更新 N，隐藏 overflow 入口。 */
.market-action-overflow-wrap {
  position: relative;
  display: none;
  flex: 0 0 auto;
}

.market-overflow-menu {
  position: absolute;
  right: 0;
  top: calc(100% + 6px);
  z-index: 35;
  min-width: 170px;
  padding: 6px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--bg-soft);
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.10);
}

.dark .market-overflow-menu {
  box-shadow: 0 14px 36px rgba(0, 0, 0, 0.36);
}

/* 窄桌面（1024px–1279px）：收纳低优先操作。AppShell 侧栏展开 232px 占去左侧，
   再叠加全局工具栏右侧 ~300px 空间，1366×768 也能舒服显示。 */
@media (min-width: 1024px) and (max-width: 1279px) {
  .market-action-overflowable {
    display: none;
  }

  .market-action-overflow-wrap {
    display: inline-flex;
  }
}

/* 搜索展开时，无论桌面多宽，都把低优先操作折叠进 overflow，确保输入框宽度可用。 */
.market-action-overflow-wrap.is-forced {
  display: inline-flex;
}

@media (min-width: 1024px) {
  .market-list-actions:has(.market-inline-search.is-open) .market-action-overflowable {
    display: none;
  }
}

.market-filter-pill.is-active {
  border-color: #000;
  background: #000;
  color: #fff;
}

.dark .market-filter-pill.is-active {
  border-color: #fff;
  background: #fff;
  color: #000;
}

.market-search-field {
  position: absolute;
  inset: 0;
  display: flex;
  width: 100%;
  height: 40px;
  align-items: center;
  gap: 9px;
  border-radius: 999px;
  border: 1px solid var(--border-strong);
  background: var(--bg-soft);
  padding: 0 12px 0 15px;
  opacity: 0;
  transform: translateX(6px);
  pointer-events: none;
  transition:
    opacity 300ms cubic-bezier(0, 0, 0.2, 1),
    transform 300ms cubic-bezier(0, 0, 0.2, 1);
}

.market-inline-search.is-open .market-search-field {
  opacity: 1;
  transform: translateX(0);
  pointer-events: auto;
}

.market-sort-dropdown {
  flex: 0 0 auto;
}

.market-sort-dropdown :deep(.market-dropdown-trigger) {
  width: 116px;
  height: 40px;
  padding: 0 16px;
  justify-content: center;
}

.market-filter-bar {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  min-width: 0;
}

@media (min-width: 1024px) {
  .market-filter-bar {
    padding-right: 300px;
  }
}

.market-filter-scroll {
  display: flex;
  min-width: 0;
  flex: 1 1 auto;
  align-items: center;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 3px;
  scrollbar-width: none;
}

.market-filter-scroll::-webkit-scrollbar {
  display: none;
}

.market-package-type-switch {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  height: 40px;
  padding: 3px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
}

.market-package-type-button {
  height: 32px;
  min-width: 66px;
  padding: 0 12px;
  border-radius: 7px;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.market-package-type-button:hover {
  color: var(--text-primary);
}

.market-package-type-button.is-active {
  background: var(--text-primary);
  color: var(--bg);
}

.market-filter-sheet-trigger {
  display: none;
  align-items: center;
  gap: 7px;
  height: 40px;
  flex: 0 0 auto;
  padding: 0 18px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 500;
}

.market-filter-count {
  display: inline-flex;
  min-width: 18px;
  height: 18px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgb(15 15 15);
  color: #fff;
  font-size: 10.5px;
  font-weight: 650;
}

.dark .market-filter-count {
  background: #fff;
  color: #000;
}

.market-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}

@media (max-width: 640px) {
  .market-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (min-width: 1024px) {
  .market-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

@media (min-width: 1280px) {
  .market-grid {
    grid-template-columns: repeat(5, minmax(0, 1fr));
  }
}

/* ── 通用按钮 ─────────────────────────────────────────── */
.market-btn-ghost {
  display: inline-flex;
  align-items: center;
  height: var(--control-height);
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 500;
  transition: background-color 160ms ease, border-color 160ms ease, color 160ms ease;
}

.market-btn-ghost:hover:not(:disabled) {
  background: var(--surface-hover);
  border-color: var(--border-strong);
}

.market-btn-ghost:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.market-btn-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-primary);
  transition: background-color 160ms ease, border-color 160ms ease;
}

.market-btn-icon:hover:not(:disabled) {
  background: var(--surface-hover);
  border-color: var(--border-strong);
}

.market-btn-icon:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.market-touch-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  flex: 0 0 auto;
  border-radius: 999px;
  color: var(--text-secondary);
  transition: background-color 140ms ease, color 140ms ease;
}

.market-touch-icon-btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.market-btn-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  background: rgb(15 15 15);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  transition: transform 140ms ease, opacity 140ms ease;
}

.dark .market-btn-primary {
  background: #fff;
  color: #000;
}

.market-btn-primary:hover:not(:disabled) {
  transform: translateY(-1px);
}

.market-btn-primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.market-btn-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
}

.market-btn-status:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.market-update-tag {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 7px;
  background: rgba(245, 158, 11, 0.14);
  color: rgb(180 83 9);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.dark .market-update-tag {
  background: rgba(245, 158, 11, 0.2);
  color: rgb(252 211 77);
}

.market-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 999px;
  color: var(--text-secondary);
  transition: background-color 140ms ease, color 140ms ease;
}

.market-icon-btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.market-input {
  display: block;
  width: 100%;
  height: 36px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--bg-soft);
  color: var(--text-primary);
  font-size: 12.5px;
  outline: none;
  transition: border-color 140ms ease;
}

.market-input:focus {
  border-color: var(--border-strong);
}

.market-input:disabled {
  opacity: 0.65;
}

/* ── 搜索框 ──────────────────────────────────────────── */
.market-search {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  height: 44px;
  padding: 0 14px;
  border-radius: 13px;
  border: 1px solid var(--border);
  background: var(--bg-soft);
  transition: border-color 160ms ease;
}

.market-search:focus-within {
  border-color: var(--border-strong);
}

/* ── 已选筛选条件 chip ─────────────────────────────────── */
.market-active-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  background: var(--surface-strong);
  color: var(--text-primary);
  font-size: 12px;
  transition: background-color 140ms ease;
}

.market-active-chip:hover {
  background: var(--surface-active);
}

/* ── 卡片 ────────────────────────────────────────────── */
.market-card {
  display: flex;
  flex-direction: column;
  min-height: 200px;
  gap: 14px;
  padding: 18px;
  border-radius: 18px;
  border: 1px solid var(--border);
  background: var(--card-bg);
  outline: none;
  transition: transform 180ms ease, border-color 180ms ease;
}

.market-card:hover {
  transform: translateY(-2px);
  border-color: var(--border-strong);
  box-shadow: none;
}

.market-card:focus-visible {
  border-color: var(--text-primary);
}

.market-card-selected {
  border-color: var(--text-primary);
}

.market-card-skeleton {
  height: 200px;
  border-radius: 18px;
  border: 1px solid var(--border);
  background: var(--surface);
  animation: market-pulse 1.4s ease-in-out infinite;
}

@keyframes market-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}

.market-card-body {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 14px;
  border-radius: 12px;
  cursor: pointer;
  outline: none;
}

.market-card-body:focus-visible {
  box-shadow: inset 0 0 0 1px var(--border-strong);
}

.market-card-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.market-region-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  flex: 0 0 auto;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.market-region-rose { background: rgba(244, 63, 94, 0.10); color: rgb(190 18 60); }
.market-region-emerald { background: rgba(16, 185, 129, 0.12); color: rgb(4 120 87); }
.market-region-sky { background: rgba(14, 165, 233, 0.12); color: rgb(2 132 199); }
.market-region-orange { background: rgba(249, 115, 22, 0.12); color: rgb(194 65 12); }
.market-region-violet { background: rgba(139, 92, 246, 0.12); color: rgb(91 33 182); }
.market-region-neutral { background: var(--surface-strong); color: var(--text-primary); }

.dark .market-region-rose { background: rgba(244, 63, 94, 0.18); color: rgb(253 164 175); }
.dark .market-region-emerald { background: rgba(16, 185, 129, 0.20); color: rgb(110 231 183); }
.dark .market-region-sky { background: rgba(14, 165, 233, 0.20); color: rgb(125 211 252); }
.dark .market-region-orange { background: rgba(249, 115, 22, 0.20); color: rgb(253 186 116); }
.dark .market-region-violet { background: rgba(139, 92, 246, 0.22); color: rgb(196 181 253); }
.dark .market-region-neutral { background: var(--surface-strong); color: var(--text-primary); }

.market-card-tags {
  display: flex;
  flex-wrap: wrap;
  min-height: 54px;
  align-content: flex-start;
  gap: 6px;
}

.market-tag {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  height: 25px;
  padding: 0 9px;
  border-radius: 8px;
  background: var(--surface);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.market-tag-red { background: rgba(244, 63, 94, 0.10); color: rgb(190 18 60); }
.market-tag-blue { background: rgba(14, 165, 233, 0.10); color: rgb(2 132 199); }
.market-tag-orange { background: rgba(249, 115, 22, 0.10); color: rgb(194 65 12); }
.market-tag-green { background: rgba(16, 185, 129, 0.10); color: rgb(4 120 87); }
.market-tag-violet { background: rgba(139, 92, 246, 0.10); color: rgb(91 33 182); }
.market-tag-neutral { background: var(--surface); color: var(--text-secondary); }

.dark .market-tag-red { background: rgba(244, 63, 94, 0.18); color: rgb(253 164 175); }
.dark .market-tag-blue { background: rgba(14, 165, 233, 0.18); color: rgb(125 211 252); }
.dark .market-tag-orange { background: rgba(249, 115, 22, 0.18); color: rgb(253 186 116); }
.dark .market-tag-green { background: rgba(16, 185, 129, 0.20); color: rgb(110 231 183); }
.dark .market-tag-violet { background: rgba(139, 92, 246, 0.22); color: rgb(196 181 253); }
.dark .market-tag-neutral { background: var(--surface); color: var(--text-secondary); }

.market-tag-rest {
  background: transparent;
  color: var(--text-tertiary);
  border: 1px dashed var(--border);
}

.market-card-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: auto;
}

.market-more-wrap {
  position: relative;
  margin-left: auto;
}

.market-more-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 999px;
  color: var(--text-tertiary);
  transition: background-color 140ms ease, color 140ms ease;
}

.market-more-btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.market-more-menu {
  position: absolute;
  right: 0;
  bottom: calc(100% + 6px);
  z-index: 30;
  min-width: 152px;
  padding: 6px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--bg-soft);
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.10);
}

.dark .market-more-menu {
  box-shadow: 0 14px 36px rgba(0, 0, 0, 0.36);
}

.market-menu-item {
  display: flex;
  width: 100%;
  align-items: center;
  padding: 7px 10px;
  border-radius: 8px;
  background: transparent;
  color: var(--text-primary);
  font-size: 12.5px;
  text-align: left;
  transition: background-color 140ms ease;
}

.market-menu-item:hover:not(:disabled) {
  background: var(--surface-hover);
}

.market-menu-item:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.market-drawer-layer {
  position: fixed;
  inset: 0;
  z-index: 120;
}

.market-drawer-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.16);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
}

.market-drawer-pane {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(440px, 94vw);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-left: 1px solid var(--border);
  background: var(--bg-soft);
  box-shadow: -18px 0 48px rgba(15, 23, 42, 0.16);
}

.dark .market-drawer-pane {
  box-shadow: -18px 0 48px rgba(0, 0, 0, 0.48);
}

.market-drawer-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--border);
}

.market-drawer-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
  padding: 14px 16px 20px;
}

.market-drawer-section {
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface);
}

.market-drawer-section:last-child {
  border-bottom: 1px solid var(--border);
}

.market-channel-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.market-channel-list--expanded {
  max-height: min(45vh, 420px);
  overflow-y: auto;
  padding-right: 4px;
}

.market-section-title {
  margin-bottom: 8px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-secondary);
  letter-spacing: 0.02em;
}

.market-drawer-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 18px calc(env(safe-area-inset-bottom) + 12px);
  border-top: 1px solid var(--border);
  background: var(--bg-soft);
}

.market-detail-more-wrap {
  position: relative;
  flex: 0 0 auto;
}

.market-detail-menu {
  bottom: calc(100% + 8px);
}

.market-drawer-enter-active,
.market-drawer-leave-active {
  transition: opacity 180ms ease;
}

.market-drawer-enter-active .market-drawer-pane,
.market-drawer-leave-active .market-drawer-pane {
  transition: transform 240ms cubic-bezier(0.32, 0.72, 0, 1);
}

.market-drawer-enter-from,
.market-drawer-leave-to {
  opacity: 0;
}

.market-drawer-enter-from .market-drawer-pane,
.market-drawer-leave-to .market-drawer-pane {
  transform: translateX(100%);
}

.market-sheet-layer {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: flex;
  align-items: flex-end;
  background: rgba(0, 0, 0, 0.18);
}

.market-filter-sheet {
  width: 100%;
  max-height: min(82vh, 720px);
  display: flex;
  flex-direction: column;
  border-radius: 18px 18px 0 0;
  border: 1px solid var(--border);
  border-bottom: 0;
  background: var(--bg-soft);
  box-shadow: 0 -16px 40px rgba(15, 23, 42, 0.12);
}

.market-sheet-header,
.market-sheet-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
}

.market-sheet-footer {
  border-top: 1px solid var(--border);
  border-bottom: 0;
  padding-bottom: calc(env(safe-area-inset-bottom) + 14px);
}

.market-sheet-body {
  overflow-y: auto;
  padding: 10px 16px 16px;
}

.market-sheet-group {
  padding: 12px 0;
}

.market-sheet-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.market-sheet-option {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface);
  padding: 0 13px;
  color: var(--text-primary);
  font-size: 13px;
}

.market-sheet-option.is-selected {
  border-color: var(--text-primary);
  background: var(--surface-active);
  font-weight: 600;
}

.market-sheet-enter-active,
.market-sheet-leave-active {
  transition: opacity 180ms ease;
}

.market-sheet-enter-active .market-filter-sheet,
.market-sheet-leave-active .market-filter-sheet {
  transition: transform 220ms cubic-bezier(0.32, 0.72, 0, 1);
}

.market-sheet-enter-from,
.market-sheet-leave-to {
  opacity: 0;
}

.market-sheet-enter-from .market-filter-sheet,
.market-sheet-leave-to .market-filter-sheet {
  transform: translateY(100%);
}

/* ── 移动端 ────────────────────────────────────────────── */
@media (max-width: 640px) {
  .market-list-head {
    align-items: flex-start;
    flex-direction: column;
    gap: 12px;
  }

  .market-filter-bar {
    margin-bottom: 12px;
  }

  .market-filter-pill {
    height: 40px;
    padding-inline: 16px;
    font-size: 13px;
  }

  .market-filter-sheet-trigger {
    display: inline-flex;
    min-width: max-content;
    height: 40px;
  }

  .market-desktop-filter {
    display: none;
  }

  .market-list-actions {
    width: 100%;
    justify-content: flex-end;
  }

  .market-inline-search {
    width: 104px;
  }

  .market-inline-search.is-open {
    width: min(100%, calc(100vw - 32px));
    flex: 1 1 auto;
  }

  .market-action-pill,
  .market-sort-dropdown :deep(.market-dropdown-trigger) {
    width: 104px;
    height: 40px;
  }

  .market-action-text,
  .market-action-update {
    width: auto;
  }

  .market-card {
    min-height: 184px;
    padding: 16px;
  }

  .market-card-tags {
    min-height: 50px;
  }

  .market-btn-primary,
  .market-btn-status,
  .market-btn-ghost {
    min-height: 40px;
  }

  .market-drawer-pane {
    width: 100vw;
    border-left: 0;
  }

  .market-drawer-header {
    padding: calc(env(safe-area-inset-top) + 10px) 16px 12px;
  }

  .market-drawer-footer {
    padding: 12px 16px calc(env(safe-area-inset-bottom) + 12px);
  }
}

/* ── 刷新按钮旋转 ─────────────────────────────────────── */
.market-spin {
  animation: market-rotate 1s linear infinite;
}

@keyframes market-rotate {
  to { transform: rotate(360deg); }
}
</style>
