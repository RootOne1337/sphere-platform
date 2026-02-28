'use client';

import React from 'react';

interface GridSparklineProps {
    data: number[];
    color?: string;
    height?: number;
}

/**
 * Легковесный спарклайн на нативном SVG.
 * Заменяет тяжёлый Recharts ResponsiveContainer, который вешал рендер
 * при 200+ устройствах (по 2 графика на строку = 400+ экземпляров).
 *
 * Никаких ResizeObserver, никаких дочерних React-деревьев —
 * просто один <svg> с <polyline>.
 */
export const GridSparkline = React.memo(function GridSparkline({
    data,
    color = '#22c55e',
    height = 24,
}: GridSparklineProps) {
    if (!data || data.length < 2) return null;

    const width = 60; // фиксированная ширина (внутренняя, растягивается через viewBox)
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;
    const padding = 2; // отступ сверху/снизу в px

    const points = data
        .map((val, i) => {
            const x = (i / (data.length - 1)) * width;
            const y = padding + ((max - val) / range) * (height - padding * 2);
            return `${x},${y}`;
        })
        .join(' ');

    return (
        <svg
            viewBox={`0 0 ${width} ${height}`}
            preserveAspectRatio="none"
            style={{ width: '100%', height, display: 'block' }}
        >
            <polyline
                points={points}
                fill="none"
                stroke={color}
                strokeWidth={1.5}
                strokeLinecap="round"
                strokeLinejoin="round"
            />
        </svg>
    );
});
