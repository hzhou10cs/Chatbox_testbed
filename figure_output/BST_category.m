%% Two side-by-side pie charts with TOP legend and BOTTOM titles (MATLAB R2025a)

% Categories (fixed order)
cats = {
    'Action Planning'
    'Problem Solving'
    'Self Monitoring'
    'Feedback Reward'
    'Education Instruction'
    'Motivational Support'
};

% Random test data (two pies)
rng(2026);
dataA = rand(1,6); dataA = dataA / sum(dataA);
dataB = rand(1,6); dataB = dataB / sum(dataB);

% Typography (consistent with previous style)
fontName      = 'Helvetica';
axFontSize    = 16;
titleFontSize = 17.6;
legFontSize   = 16;

% 6-color palette (first three aligned with your line plot)
cBlue   = [0.0353 0.5176 0.8902];
cGreen  = [0.4667 0.6745 0.1882];
cOrange = [0.9098 0.2549 0.0941];
cPurple = [0.4941 0.1843 0.5569];
cGray   = [0.4500 0.4500 0.4500];
cGold   = [0.9290 0.6940 0.1250];
cmap = [cBlue; cGreen; cOrange; cPurple; cGray; cGold];


% Figure (make it wider to enlarge pies)
fig = figure('Color','w','Units','pixels','Position',[100 100 1000 520]);

% ---------- Manual layout (normalized positions) ----------
% Legend strip (thin)
axLeg = axes(fig, 'Units','normalized', 'Position',[0.05 0.90 0.90 0.08]);
axis(axLeg, 'off'); hold(axLeg, 'on');

% Two pie axes (move upward to reduce gap)
ax1 = axes(fig, 'Units','normalized', 'Position',[0.07 0.14 0.40 0.74]);
ax2 = axes(fig, 'Units','normalized', 'Position',[0.53 0.14 0.40 0.74]);

% Apply colormap
colormap(fig, cmap);

% ---------- Legend (use dummy patches so legend always shows) ----------
hp = gobjects(1,6);
for k = 1:6
    hp(k) = patch(axLeg, NaN, NaN, cmap(k,:), 'EdgeColor','w', 'LineWidth',1);
end

leg = legend(axLeg, hp, cats, ...
    'Units','normalized', ...
    'Location','north', ...
    'Orientation','horizontal', ...
    'NumColumns', 3);
set(leg, 'Box','on', 'FontName',fontName, 'FontSize',legFontSize, 'FontWeight','bold');

% ---------- Pie A ----------
axes(ax1);
h1 = pie(ax1, dataA);
axis(ax1, 'equal');
colormap(ax1, cmap);

txt1 = findobj(h1, 'Type','text');
set(txt1, 'FontName',fontName, 'FontSize',axFontSize, 'FontWeight','bold');

p1 = h1(1:2:end);
set(p1, 'EdgeColor','w', 'LineWidth',1);

% ---------- Pie B ----------
axes(ax2);
h2 = pie(ax2, dataB);
axis(ax2, 'equal');
colormap(ax2, cmap);

txt2 = findobj(h2, 'Type','text');
set(txt2, 'FontName',fontName, 'FontSize',axFontSize, 'FontWeight','bold');

p2 = h2(1:2:end);
set(p2, 'EdgeColor','w', 'LineWidth',1);

% ---------- Bottom titles (annotation with clamped y to avoid out-of-range) ----------
drawnow;  % ensure positions are final
ax1.Position = [0.06 0.14 0.4 0.7];
ax2.Position = [0.52 0.14 0.4 0.7];
pos1 = ax1.Position;  % normalized figure units
pos2 = ax2.Position;

titleH = 0.06;        % title box height
offset = 0.08;        % how far below axes
y1 = max(0.001, pos1(2) - offset);   % clamp to [0,1]
y2 = max(0.001, pos2(2) - offset);

annotation(fig, 'textbox', [pos1(1), y1, pos1(3), titleH], ...
    'String', 'Overall BCT Ratio', 'EdgeColor','none', ...
    'HorizontalAlignment','center', 'VerticalAlignment','middle', ...
    'FontName',fontName, 'FontSize',titleFontSize, 'FontWeight','bold');

annotation(fig, 'textbox', [pos2(1), y2, pos2(3), titleH], ...
    'String','Repetitive Ratio by BCT', 'EdgeColor','none', ...
    'HorizontalAlignment','center', 'VerticalAlignment','middle', ...
    'FontName',fontName, 'FontSize',titleFontSize, 'FontWeight','bold');

% Optional export
% exportgraphics(fig,'two_pies.png','Resolution',300);
% exportgraphics(fig,'two_pies.pdf','ContentType','vector');