%% Radar chart (6 dimensions, score 1-7), 3 benchmarks
% Requirements:
% - Radar on the left, legend on the right
% - 6 metrics (labels below)
% - Style: Helvetica + bold, thicker lines, clean grid (similar to your sample)
% MATLAB R2025a

clear; clc;

% ---------------- Metrics (order matters) ----------------
metrics = {
    'Perceived helpfulness'
    'Actionability & Clarity'
    'Proactive Guidance'
    'Fit to User Constraints'
    'Continuity & Coherence'
    'Autonomy &    '
};

nDim = numel(metrics);
nBench = 3;
benchNames = {'Benchmark A','Benchmark B','Benchmark C'};

% ---------------- Example data (1..7) for testing ----------------
% Replace with your real scores later (each row: one benchmark, 6 values)
rng(2026);
S = 1 + 6*rand(nBench, nDim);     % continuous in [1,7]
S = round(S, 1);                  % keep one decimal (optional)

% ---------------- Style ----------------
fontName = 'Helvetica';
axFontSize = 16;
labelFontSize = 16;     % metric labels
legFontSize = 16;

cBlue   = [0.0353, 0.5176, 0.8902];
cRed  = [0.9098, 0.2549, 0.0941];
cOrange = [0.9294, 0.6941, 0.1255];
colors = [cRed; cBlue;  cOrange];

lineW = 3;

% ---------------- Layout: left radar axis + right legend area ----------------
fig = figure('Color','w','Units','pixels','Position',[100 100 900 560]);

% Leave space at bottom for legend
ax = polaraxes(fig, 'Units','normalized', 'Position',[0.08 0.22 0.84 0.72]);
hold(ax,'on');

% Polar axes config
ax.ThetaZeroLocation = 'top';
ax.ThetaDir = 'clockwise';

ax.RLim  = [1 7];
ax.RTick = 1:7;

% Angles for the 6 vertices (and close the polygon)
thetaBase = (0:nDim-1) / nDim * 2*pi;
thetaPoly = [thetaBase, thetaBase(1)];   % close

ax.ThetaTick = rad2deg(thetaBase);
ax.ThetaTickLabel = metrics;

ax.FontName = fontName;
ax.FontSize = axFontSize;
ax.FontWeight = 'bold';

ax.GridAlpha = 0.25;
ax.LineWidth = 1;

% Allow text outside the polar circle (for the second line label)
ax.Clipping = 'off';

% ----- Plot fills (theta-r patch) + lines (polarplot) -----
hLine = gobjects(1, nBench);

for b = 1:nBench
    rPoly = [S(b,:), S(b,1)];   % close

    % Fill FIRST (exclude from legend)
    hPatch = patch(ax, thetaPoly, rPoly, colors(b,:), ...
        'FaceAlpha', 0.10, 'EdgeColor', 'none', 'HandleVisibility','off');

    % Line SECOND (used in legend)
    hLine(b) = polarplot(ax, thetaPoly, rPoly, '-', ...
        'LineWidth', lineW, 'Color', colors(b,:));
end

% ----- Add second line for the last metric label -----
% Place it slightly outside the outer circle. Tune these two if needed.
rLabel1 = ax.RLim(2) * 1.13;  % radius for first line (tick label already at default)
rLabel2 = ax.RLim(2) * 1.05;  % radius for second line (slightly inward/outward)

theta6 = thetaBase(6);

% Put second line using text() in polar coordinates (theta,r)
text(ax, theta6, rLabel2, 'Non-Intrusiveness', ...
    'HorizontalAlignment','center', 'VerticalAlignment','middle', ...
    'FontName',fontName, 'FontSize',axFontSize, 'FontWeight','bold');

% Optional: push the tick label outward a bit by adding an invisible text,
% but usually the default is fine. If you want more separation, uncomment:
% text(ax, theta6, rLabel1, ' ', 'Clipping','off');

% ----- Legend: bottom, 1 row, centered -----
leg = legend(ax, hLine, benchNames, ...
    'Location','southoutside', 'Orientation','horizontal', 'NumColumns', 3);

set(leg, 'Box','on', 'FontName',fontName, 'FontSize',legFontSize, 'FontWeight','bold');

% Force center alignment (robust)
leg.Units = 'normalized';
leg.Position(1) = 0.5 - leg.Position(3)/2;
leg.Position(2) = 0.08;