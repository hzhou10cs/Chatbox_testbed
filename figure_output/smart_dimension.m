%% (2R) Main Fig 2 Replacement: Radar chart for SMART dimensions (3 benchmarks)
% - Uses per-user aggregation first, then benchmark-level mean
% - Radar chart avoids overlapping markers/errorbars on a 5-dim axis
% - Colors: A/B/C = [cRed; cBlue; cOrange]
% MATLAB R2025a

clear; clc;
load('sim_smart.mat', 'scores','benchNames','dimNames','nUsers','nBench','colors');

% ---------------- Style ----------------
fontName = 'Helvetica';
axFontSize = 16;
legFontSize = 16;

lineW = 3;
fillAlpha = 0.10;    % polygon fill alpha
gridAlpha = 0.25;

% Optional: show CI band polygon (OFF by default for readability)
showCI = false;      % set true if you want ±95% CI shown
z = 1.96;

% ---------------- Aggregate: per-user -> benchmark mean ----------------
% dimMean(u,b,k) = mean over domains & sessions for that dimension
dimMean = squeeze(mean(scores, [3 4]));   % (u,b,k)

mu = squeeze(mean(dimMean, 1));           % (b,k)
sd = squeeze(std(dimMean, 0, 1));         % (b,k)
se = sd ./ sqrt(nUsers);
ci = z * se;                              % (b,k)

% ---------------- Radar geometry ----------------
nDim = size(mu,2);            % should be 5
thetaBase = (0:nDim-1)/nDim * 2*pi;
thetaPoly = [thetaBase, thetaBase(1)];

% Close polygons
muPoly = [mu, mu(:,1)];
ciPoly = [ci, ci(:,1)];

% ---------------- Figure + polar axes ----------------
fig = figure('Color','w', 'Position',[100 100 600 500]);

ax = polaraxes(fig, 'Units','normalized', 'Position',[0.08 0.20 0.84 0.75]);
hold(ax,'on');

ax.ThetaZeroLocation = 'top';
ax.ThetaDir = 'clockwise';

ax.RLim  = [0 5];
ax.RTick = 0:1:5;

% Put dimension labels around
ax.ThetaTick = rad2deg(thetaBase);

% Short labels to avoid crowding (recommended for radar)
% If you prefer full dimNames, replace the cell array below with dimNames.
ax.ThetaTickLabel = {'S','M','A','R','T'};

ax.FontName = fontName;
ax.FontSize = axFontSize;
ax.FontWeight = 'bold';

ax.GridAlpha = gridAlpha;
ax.LineWidth = 1;
ax.Clipping = 'off';

% ---------------- Plot: fill + line (and optional CI band) ----------------
hLine = gobjects(1, nBench);

for b = 1:nBench
    r = muPoly(b,:);

    % Fill aligned with polar axes: use patch(theta,r) directly
    patch(ax, thetaPoly, r, colors(b,:), ...
        'FaceAlpha', fillAlpha, 'EdgeColor', 'none', 'HandleVisibility','off');

    % Optional CI band: draw (mu-ci) to (mu+ci) as a ring-like polygon
    if showCI
        rLo = max(0, r - ciPoly(b,:));
        rHi = min(5, r + ciPoly(b,:));
        % Construct a closed band polygon
        thetaBand = [thetaPoly, fliplr(thetaPoly)];
        rBand = [rHi, fliplr(rLo)];
        patch(ax, thetaBand, rBand, colors(b,:), ...
            'FaceAlpha', 0.08, 'EdgeColor', 'none', 'HandleVisibility','off');
    end

    % Mean polygon line (for legend)
    hLine(b) = polarplot(ax, thetaPoly, r, '-', 'LineWidth', lineW, 'Color', colors(b,:));
end

% ---------------- Legend: bottom, centered, 1 row ----------------
leg = legend(ax, hLine, benchNames, ...
    'Location','southoutside', ...
    'Orientation','horizontal', ...
    'NumColumns', 3);
set(leg, 'Box','on', 'FontName',fontName, 'FontSize',legFontSize, 'FontWeight','bold');

% Force center alignment (robust)
leg.Units = 'normalized';
leg.Position(1) = 0.5 - leg.Position(3)/2;
leg.Position(2) = 0.05;

% Optional: if you want to show full dimension names somewhere else,
% you can add a small text box annotation on the right or below.
