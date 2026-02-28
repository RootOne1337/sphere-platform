'use client';

import { LineChart, Line, ResponsiveContainer, YAxis } from 'recharts';

interface GridSparklineProps {
    data: number[];
    color?: string;
    height?: number;
}

export function GridSparkline({ data, color = '#22c55e', height = 24 }: GridSparklineProps) {
    // Трансформируем массив чисел в формат Recharts
    const chartData = data.map((val, i) => ({ value: val, index: i }));

    return (
        <div style={{ height, width: '100%' }}>
            <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
                <LineChart data={chartData}>
                    <YAxis domain={['dataMin - 10', 'dataMax + 10']} hide />
                    <Line
                        type="monotone"
                        dataKey="value"
                        stroke={color}
                        strokeWidth={1.5}
                        dot={false}
                        isAnimationActive={false} // Отключаем для перформанса в виртуализированной таблице
                    />
                </LineChart>
            </ResponsiveContainer>
        </div>
    );
}
