import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

type MonthlyPoint = { month: number; burned_area_ha: number; burned_area_km2?: number };

export default function MonthlyBurnChart({ data }: { data: MonthlyPoint[] }) {
  const chartData = data.map((d) => ({ ...d, label: months[(d.month ?? 1) - 1] ?? String(d.month) }));
  return (
    <div className="mt-3 h-44 rounded-2xl border border-slate-200 bg-gradient-to-b from-white to-amber-50/40 p-3">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 6, right: 10, bottom: 0, left: -18 }}>
          <defs>
            <linearGradient id="burnAreaFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#d97706" stopOpacity={0.34} />
              <stop offset="95%" stopColor="#d97706" stopOpacity={0.04} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="rgba(100, 116, 139, 0.16)" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} interval={1} />
          <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v) => `${Math.round(Number(v) / 1000)}k`} />
          <Tooltip
            cursor={{ stroke: 'rgba(180, 83, 9, 0.45)' }}
            contentStyle={{ background: '#ffffff', border: '1px solid rgba(33, 45, 63, 0.13)', borderRadius: 14, color: '#172033', boxShadow: '0 12px 32px rgba(37,44,57,0.16)' }}
            formatter={(value) => [`${Number(value).toLocaleString()} ha`, 'Burned area']}
            labelFormatter={(label) => `${label} 2024`}
          />
          <Area type="monotone" dataKey="burned_area_ha" stroke="#b45309" strokeWidth={2.2} fill="url(#burnAreaFill)" dot={false} activeDot={{ r: 4 }} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
