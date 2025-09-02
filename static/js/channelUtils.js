// ChannelUtils: shared helpers for channel sorting and previews
window.App = window.App || {};

App.ChannelUtils = (function() {
    'use strict';

    function getSortMode() {
        const select = document.getElementById('channels-sort-mode');
        return (select && select.value) ? String(select.value) : 'name';
    }

    function deriveOnValuePreview(channelData) {
        if (!channelData) return '';
        try {
            const type = channelData.osc_type || 'float';
            if (type === 'string') {
                const strs = Array.isArray(channelData.osc_strings) ? channelData.osc_strings : [];
                return String((strs.length > 1 ? strs[1] : (strs.length > 0 ? strs[0] : '')));
            }
            if (Array.isArray(channelData.range) && channelData.range.length === 2) {
                return String(channelData.range[1]);
            }
            if (channelData.max_value !== undefined || channelData.range_max !== undefined) {
                return String(channelData.max_value !== undefined ? channelData.max_value : channelData.range_max);
            }
            return '';
        } catch (e) { return ''; }
    }

    function sortChannelEntries(entries, mode) {
        const sortMode = mode || getSortMode();
        // For "recent", preserve insertion order (object order from backend) but reverse so newest are first.
        if (sortMode === 'recent') {
            return entries.slice().reverse();
        }
        return entries.slice().sort(([nameA, chA], [nameB, chB]) => {
            if (sortMode === 'address') {
                const a = (chA && chA.osc_address) ? String(chA.osc_address) : '';
                const b = (chB && chB.osc_address) ? String(chB.osc_address) : '';
                return a.localeCompare(b);
            }
            if (sortMode === 'on') {
                const a = deriveOnValuePreview(chA);
                const b = deriveOnValuePreview(chB);
                return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
            }
            return String(nameA).localeCompare(String(nameB));
        });
    }

    return {
        getSortMode,
        deriveOnValuePreview,
        sortChannelEntries
    };
})();


